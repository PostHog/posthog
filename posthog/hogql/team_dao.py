"""Team Data Access Object interface for HogQL.

This module defines the abstract interface for accessing team data
within the HogQL subsystem, allowing for clean separation from
the Django ORM and enabling easier testing and mocking.
"""

from abc import ABC, abstractmethod
from typing import Optional

from .team_dto import TeamDTO


class TeamDAO(ABC):
    """Abstract Data Access Object for Team entities.

    This interface defines how HogQL code should access team data,
    providing a clean abstraction layer that can be implemented
    using Django ORM, in-memory stores, or other persistence mechanisms.
    """

    @abstractmethod
    def get_by_id(self, team_id: int) -> Optional[TeamDTO]:
        """Retrieve a team by its ID.

        Args:
            team_id: The unique identifier for the team

        Returns:
            TeamDTO if found, None otherwise
        """
        pass
