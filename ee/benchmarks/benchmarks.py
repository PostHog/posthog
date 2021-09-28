# from .helpers import *
# from ee.clickhouse.client import sync_execute


# @benchmark_clickhouse
# def foobar():
#     client.sync_execute("SELECT sleep(1)")


class TimeSuite:
    def setup(self):
        self.d = {}
        for x in range(500):
            self.d[x] = None

    def time_keys(self):
        for key in self.d.keys():
            pass

    def time_values(self):
        for value in self.d.values():
            pass

    def time_range(self):
        d = self.d
        for key in range(500):
            x = d[key]

    def time_foo(self):
        import time

        s = []
        for i in range(50000):
            s.append(2 ** i)
