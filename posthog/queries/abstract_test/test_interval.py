from abc import ABC, abstractmethod


class AbstractIntervalTest(ABC):
    @abstractmethod
    def test_minute_interval(self):
        pass

    @abstractmethod
    def test_hour_interval(self):
        pass

    @abstractmethod
    def test_day_interval(self):
        pass

    @abstractmethod
    def test_week_interval(self):
        pass

    @abstractmethod
    def test_month_interval(self):
        pass

    @abstractmethod
    def test_interval_rounding(self):
        pass
