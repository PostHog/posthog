from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from posthog.caching.fetch_from_cache import SplitCachedResponse
from posthog.query_cache import freshness_index


class QueryCacheManagerBase(ABC):
    """
    Abstract base class for query cache managers.

    All cache managers use Redis for sorted set operations (stale insights tracking)
    but can use different storage backends for the actual cache data (Django cache, S3, etc.).
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

    @classmethod
    def get_stale_insights(cls, *, team_id: int, limit: Optional[int] = None) -> list[str]:
        return freshness_index.get_stale_insights(team_id=team_id, limit=limit)

    @classmethod
    def clean_up_stale_insights(cls, *, team_id: int, threshold: datetime) -> None:
        freshness_index.clean_up_stale_insights(team_id=team_id, threshold=threshold)

    def update_target_age(self, target_age: datetime) -> None:
        freshness_index.update_target_age(
            team_id=self.team_id, insight_id=self.insight_id, dashboard_id=self.dashboard_id, target_age=target_age
        )

    def remove_last_refresh(self) -> None:
        freshness_index.remove_last_refresh(
            team_id=self.team_id, insight_id=self.insight_id, dashboard_id=self.dashboard_id
        )

    @abstractmethod
    def set_cache_data(self, *, response: dict, target_age: Optional[datetime]) -> None:
        """Store query results in cache."""
        pass

    @abstractmethod
    def get_cache_data(self) -> Optional[dict]:
        """Retrieve query results from cache."""
        pass

    def get_cache_data_split(self) -> Optional[SplitCachedResponse]:
        """Retrieve cached results, keeping the results segment as raw bytes when the backend supports it."""
        data = self.get_cache_data()
        if data is None:
            return None
        return SplitCachedResponse(header=data, results_bytes=None)
