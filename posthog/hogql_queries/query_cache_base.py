from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Optional

from posthog import redis


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
        self.redis_client = redis.get_client()

    @property
    def identifier(self) -> str:
        """Unique identifier for tracking insight freshness."""
        return f"{self.insight_id}:{self.dashboard_id or ''}"

    @classmethod
    def _redis_key_prefix(cls) -> str:
        """Redis key prefix for cache timestamps. Can be overridden by subclasses."""
        return "cache_timestamps"

    @classmethod
    def get_stale_insights(cls, *, team_id: int, limit: Optional[int] = None) -> list[str]:
        """
        Use redis sorted set to get stale insights. We sort by the timestamp and get the insights that are
        stale compared to the current time.

        We start with the least stale insights: Because we want to keep in mind
        that we might not have enough time to refresh all insights. This way, and only if we don't manage to refresh
        all insights, we try our best to keep a number of insights fully up-to-date, instead of only achieving to
        refresh the most stale ones while failing to refresh the rest. Should an insight be refreshed by user or other
        means it will be the freshest anyway again.

        It is accepted that we store all combinations of insight + dashboard, even if the dashboard might not have
        additional filters (which makes this dashboard insight the same as the single one). This is easily mitigated by
        the fact we should have the very same cache key for these and we calculate the insights in sequence. Thus, the
        first calculation to refresh it will refresh all of them.
        """
        current_time = datetime.now(UTC)
        redis_key = f"{cls._redis_key_prefix()}:{team_id}"
        # get least stale insights first
        if limit is not None:
            insights = redis.get_client().zrevrangebyscore(
                name=redis_key, max=current_time.timestamp(), min="-inf", start=0, num=limit
            )
        else:
            insights = redis.get_client().zrevrangebyscore(name=redis_key, max=current_time.timestamp(), min="-inf")
        return [insight.decode("utf-8") for insight in insights]

    @classmethod
    def clean_up_stale_insights(cls, *, team_id: int, threshold: datetime) -> None:
        """
        Remove all stale insights that are older than the given timestamp.
        """
        redis_key = f"{cls._redis_key_prefix()}:{team_id}"
        redis.get_client().zremrangebyscore(
            redis_key,
            "-inf",
            threshold.timestamp(),
        )

    def update_target_age(self, target_age: datetime) -> None:
        """Update the target age for insight freshness tracking using Redis sorted sets."""
        if not self.insight_id:
            return

        redis_key = f"{self._redis_key_prefix()}:{self.team_id}"
        self.redis_client.zadd(
            redis_key,
            {self.identifier: target_age.timestamp()},
        )

    def remove_last_refresh(self) -> None:
        """Remove insight from freshness tracking using Redis sorted sets."""
        if not self.insight_id:
            return

        redis_key = f"{self._redis_key_prefix()}:{self.team_id}"
        self.redis_client.zrem(redis_key, self.identifier)

    @abstractmethod
    def set_cache_data(self, *, response: dict, target_age: Optional[datetime]) -> None:
        """Store query results in cache."""
        pass

    @abstractmethod
    def get_cache_data(self) -> Optional[dict]:
        """Retrieve query results from cache."""
        pass
