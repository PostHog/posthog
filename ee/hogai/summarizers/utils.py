from abc import ABC, abstractmethod


class Summarizer(ABC):
    @property
    def summary(self) -> str:
        return self._generate_summary()

    @abstractmethod
    def _generate_summary(self) -> str:
        pass
