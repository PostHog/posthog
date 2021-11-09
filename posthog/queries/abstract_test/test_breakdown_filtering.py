from abc import ABC, abstractmethod


class AbstractBreakdownTest(ABC):
    @abstractmethod
    def test_breakdown_event_property(self):
        pass

    @abstractmethod
    def test_breakdown_person_property_property(self):
        pass

    @abstractmethod
    def test_breakdown_cohort_property(self):
        pass

    @abstractmethod
    def test_breakdown_multiple_property(self):
        pass
