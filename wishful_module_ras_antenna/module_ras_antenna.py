import logging
import random
import time
import queue

import serial
import logging
import time

import wishful_upis as upis
import wishful_framework as wishful_module


__author__ = "Domenico Garlisi"
__copyright__ = "Copyright (c) 2015"
__version__ = "0.1.0"
__email__ = "{domenico.garlisi}@cnit.it"

EXIT_SUCCESS = 0
EXIT_FAILURE = -1
ERROR_UNSYNC = -2

WISHFUL_MODE = "w"

HW_ID = "0403:6010"  # vendor and product id
DEV_PRODUCT = "AD-WSFL-U"
DEV_MANUFACTURER = "Adant"
DEV_WELCOME = b'-- WiSHFUL UART RECEIVER --'
DEV_SERIAL = 'ADK1EVUB'
BAUDRATE = 115200

@wishful_module.build_module
class RasAntennaModule(wishful_module.AgentModule):
    def __init__(self):
        super(RasAntennaModule, self).__init__()
        self.log = logging.getLogger('RasAntennaModule')

        import serial.tools.list_ports
        devices = []
        for dev in serial.tools.list_ports.grep(HW_ID):
            requirements = ((dev.manufacturer == DEV_MANUFACTURER
                             and dev.product == DEV_PRODUCT)
                            or dev.serial_number == DEV_SERIAL)
            if not requirements:
                self.log.debug("Ignoring serial device with same Hardware ID but missing requirements:\n"
                              "\tManufacturer:%s\n"
                              "\tProduct:%s", dev.manufacturer, dev.product)
                continue
            else:
                # Test the device connection
                with serial.Serial(dev.device, BAUDRATE,
                                   write_timeout=1,
                                   timeout=1) as ser:
                    ser.write(b'x')
                    response = ser.readline()
                    if DEV_WELCOME in response:
                        # Correct device
                        devices.append(dev)
                    else:
                        self.log.debug("Unexpecetd device response: %s",
                                     str(response))
        if not devices:
            self.dev = None
            self.log.error("SmartAntenna controller %s not found!", DEV_PRODUCT)
            for dev in serial.tools.list_ports.comports():
                self.log.error("%s", dev.description)
            raise Exception("SmartAntenna controller %s not found!", DEV_PRODUCT)
        for dev in devices:
            self.log.info(DEV_PRODUCT + " found on " + dev.device)
        if len(devices) > 1:
            self.log.error("MULTIPLE " + DEV_PRODUCT + " found!")
            raise Exception("Multiple " + DEV_PRODUCT + " found!")

        self.dev = devices[0]
        self.ser = serial.Serial()
        self.ser.port = dev.device
        self.ser.baudrate = BAUDRATE
        self.ser.timeout = 1
        self.ser.write_timeout = 2
        self.ser.xonxoff = True
        self.ser.open()
        self.log.info("Connected to: " + self.ser.port)
        self.set_mode(WISHFUL_MODE)

    @wishful_module.bind_function(upis.ras_antenna.radio.set_mode)
    def set_mode(self, mode=WISHFUL_MODE):
        if mode == WISHFUL_MODE:
            self.ser.write(b'w')
            response = self.ser.readlines()
            status = any([b'WiSHFUL mode activated' in x for x in response])
            if status:
                self.log.debug("Controller set in WISHFUL_MODE: %s", status)
            else:
                self.log.warning("Unable to set controller in WISHFUL_MODE:\n"
                               "Response: %s:", response)
            return status


    @wishful_module.bind_function(upis.ras_antenna.radio.write_sequence)
    def write_sequence(self, seq):
        if self.ser.is_open:
            self.ser.write(bytes(seq, 'utf8'))
            time.sleep(0.5)
            response = self.ser.read_all()
            self.log.debug(str(response))
            if not ("successful command received" in str(response)):
                self.log.warning(str(response))


    @wishful_module.bind_function(upis.ras_antenna.radio.test_leds)
    def test_leds(self):
        """ Test proper LED functionality

        :return: None
        """
        self.log.info("Starting test led mode...")
        sequence = [[1, 0, 0, 0], [0, 1, 0, 0],
                    [0, 0, 1, 0], [0, 0, 0, 1],
                    [0, 0, 0, 0]]
        delay = 0.25
        for band in [2, 5]:
            for a1, a2, a3, a4 in sequence:
                self.set_sas_conf(band, a1, a2, a3, a4)
                time.sleep(delay)
        #reverse
        for band in [5, 2]:
            for a4, a3, a2, a1 in sequence:
                self.set_sas_conf(band, a1, a2, a3, a4)
                time.sleep(delay)


    @wishful_module.bind_function(upis.ras_antenna.radio.set_sas_conf)
    def set_sas_conf(self, band, conf_ant1, conf_ant2, conf_ant3, conf_ant4):
        """ Set the configuration for each smart-antenna

        :param band: (int) WiFi band, 2 or 5
        :param conf_ant1: (int) direction for antenna 1
        :param conf_ant2: (int) direction for antenna 2
        :param conf_ant3: (int) direction for antenna 3
        :param conf_ant4: (int) direction for antenna 4
        :return:
        """
        self.log.debug("Set Antenna command: %s", str(band))

        antennas = [conf_ant1, conf_ant2, conf_ant3, conf_ant4]
        # Validate
        if not self.ser.is_open:
            self.log.error("Impossible to set_sas_conf")
            self.log.error("Connection not available")
            return -1
        if not band in [2, 5]:
            self.log.error("Impossible to set_sas_conf")
            self.log.error("Unexpceted band value: %s", str(band))
            return -2
        try:
            if not all([a >= 0 and a <= 8 for a in antennas]):
                self.log.error("Impossible to set_sas_conf")
                self.log.error("Unexpceted antennas value: %s", str(antennas))
                return -3
        except TypeError:
            self.log.error("Impossible to set_sas_conf")
            self.log.error("Unexpceted antenna type (must be int): %s", str(antennas))
            return -4
        else:
            self.log.debug("Input command: %s, %s", str(band), str(antennas))

        command = "W" + str(band) + "".join([str(x) for x in antennas]) + "t"
        return self.write_sequence(command)


    @wishful_module.bind_function(upis.ras_antenna.radio.reset_controller)
    def reset_controller(self):
        """ Reset the controller serial interface.
        This function is sometimes blocking.

        :return: (bool) the serial interface status
        """
        self.log.debug("Resetting the controller...")
        self.ser.close()
        self.log.debug("Wait one sec...")
        time.sleep(1)
        self.log.debug("Open again")
        self.ser.open()
        return self.ser.is_open





    # def before_set_channel(self):
    #     self.log.info("This function is executed before set_channel".format())
    #
    # def after_set_channel(self):
    #     self.log.info("This function is executed after set_channel".format())
    #
    # @wishful_module.before_call(before_set_channel)
    # @wishful_module.after_call(after_set_channel)
    # @wishful_module.bind_function(upis.wifi.radio.set_channel)
    # def set_channel(self, channel):
    #     self.log.info("Simple Module sets channel: {} on interface: {}".format(channel, self.interface))
    #     self.channel = channel
    #     return ["SET_CHANNEL_OK", channel, 0]
    # @wishful_module.bind_function(upis.wifi.radio.get_channel)
    # def get_channel(self):
    #     self.log.debug("Simple Module gets channel of interface: {}".format(self.interface))
    #     return self.channel
    #
    #
    # @wishful_module.run_in_thread()
    # def before_get_rssi(self):
    #     self.log.info("This function is executed before get_rssi".format())
    #     self.stopRssi = False
    #     while not self.stopRssi:
    #         time.sleep(0.2)
    #         sample = random.randint(-90, 30)
    #         self.rssiSampleQueue.put(sample)
    #
    #     #empty sample queue
    #     self.log.info("Empty sample queue".format())
    #     while True:
    #         try:
    #             self.rssiSampleQueue.get(block=True, timeout=0.1)
    #         except:
    #             self.log.info("Sample queue is empty".format())
    #             break
    #
    # def after_get_rssi(self):
    #     self.log.info("This function is executed after get_rssi".format())
    #     self.stopRssi = True
    #
    # @wishful_module.generator()
    # @wishful_module.before_call(before_get_rssi)
    # @wishful_module.after_call(after_get_rssi)
    # def get_rssi(self):
    #     self.log.debug("Get RSSI".format())
    #     while True:
    #         yield self.rssiSampleQueue.get()
