from abc import ABC, abstractmethod


class AbstractPropertyFilteringTest(ABC):
    @abstractmethod
    def test_event_property_filtering(self):
        pass

    @abstractmethod
    def test_multiple_event_property_filtering(self):
        pass

    @abstractmethod
    def test_person_property_filtering(self):
        pass

    @abstractmethod
    def test_mixed_person_event_property_filtering(self):
        pass

    @abstractmethod
    def test_cohort_property_filtering(self):
        pass

    @abstractmethod
    def test_multiple_cohort_property_fitlering(self):
        pass
