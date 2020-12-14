from abc import ABC, abstractmethod


class AbstractCompareTest(ABC):
    @abstractmethod
    def test_compare(self):
        pass
