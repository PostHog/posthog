from abc import ABC, abstractmethod


class AbstractTimerangeTest(ABC):
    @abstractmethod
    def test_today_timerange(self):
        pass

    @abstractmethod
    def test_yesterday_timerange(self):
        pass

    @abstractmethod
    def test_last24hours_timerange(self):
        pass

    @abstractmethod
    def test_last48hours_timerange(self):
        pass

    @abstractmethod
    def test_last7days_timerange(self):
        pass

    @abstractmethod
    def test_last14days_timerange(self):
        pass

    @abstractmethod
    def test_last30days_timerange(self):
        pass

    @abstractmethod
    def test_last90days_timerange(self):
        pass

    @abstractmethod
    def test_this_month_timerange(self):
        pass

    @abstractmethod
    def test_previous_month_timerange(self):
        pass

    @abstractmethod
    def test_year_to_date_timerange(self):
        pass

    @abstractmethod
    def test_all_time_timerange(self):
        pass

    @abstractmethod
    def test_custom_range_timerange(self):
        pass
