from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional


class QueryCacheManagerBase(ABC):
    """
    Abstract base class for query cache managers.

    Provides a common interface for different cache backends (Redis, S3, etc.)
    to store and retrieve query results with TTL and stale insight tracking.
    """

    def __init__(
        self,
        *,
        team_id: int,
        cache_key: str,
        insight_id: Optional[int] = None,
        dashboard_id: Optional[int] = None,
    ):
        self.team_id = team_id
        self.cache_key = cache_key
        self.insight_id = insight_id
        self.dashboard_id = dashboard_id

    @property
    def identifier(self) -> str:
        """Unique identifier for tracking insight freshness."""
        return f"{self.insight_id}:{self.dashboard_id or ''}"

    @abstractmethod
    def get_cache_data(self) -> Optional[dict]:
        """Retrieve cached query results."""
        pass

    @abstractmethod
    def set_cache_data(self, *, response: dict, target_age: Optional[datetime]) -> None:
        """Store query results with optional target age for freshness tracking."""
        pass

    @abstractmethod
    def update_target_age(self, target_age: datetime) -> None:
        """Update the target age for insight freshness tracking."""
        pass

    @abstractmethod
    def remove_last_refresh(self) -> None:
        """Remove insight from freshness tracking."""
        pass

    @staticmethod
    @abstractmethod
    def get_stale_insights(*, team_id: int, limit: Optional[int] = None) -> list[str]:
        """Get list of stale insights that need refreshing."""
        pass

    @staticmethod
    @abstractmethod
    def clean_up_stale_insights(*, team_id: int, threshold: datetime) -> None:
        """Remove stale insights older than threshold."""
        pass
