from abc import ABC, abstractmethod
from functools import cached_property

from posthog.models import Team


class Summarizer(ABC):
    _team: Team

    def __init__(self, team: Team):
        self._team = team

    @cached_property
    def summary(self) -> str:
        return self._generate_summary()

    @abstractmethod
    def _generate_summary(self) -> str:
        pass

    @staticmethod
    def join_conditions(conditions: list[str], separator: str = " AND ") -> str:
        """
        Join a list of conditions with a separator.

        Args:
            conditions: The list of conditions to join. Default is ` AND `.
            separator: The separator to join the conditions with.

        Returns:
            The joined conditions.
        """
        return separator.join(conditions)

    @staticmethod
    def parenthesize(condition: str) -> str:
        """
        Prepend and append `(` and `)` to a string.

        Args:
            condition: The string to add parentheses to.

        Returns:
            The condition with `(` and `)` prepended and appended.
        """
        return f"({condition})"

    @staticmethod
    def pluralize(noun: str, count: int) -> str:
        """
        Append `s` to a noun based on the count.

        Args:
            noun: The noun to pluralize.
            count: The count of the noun.

        Returns:
            The pluralized noun.
        """
        return f"{noun}s" if count != 1 else noun
