from abc import ABC, abstractmethod


class AbstractGraphTypeTest(ABC):
    @abstractmethod
    def test_linear_graph(self):
        pass

    @abstractmethod
    def test_cumulative_graph(self):
        pass

    @abstractmethod
    def test_table(self):
        pass

    @abstractmethod
    def test_pie(self):
        pass

    @abstractmethod
    def test_bar(self):
        pass
