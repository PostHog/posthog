from datetime import datetime, UTC
from typing import Optional

from django.conf import settings
from django.core.cache import cache

from posthog import redis
from posthog.cache_utils import OrjsonJsonSerializer
from posthog.utils import get_safe_cache
from posthog.hogql_queries.query_cache_base import QueryCacheManagerBase


class RedisQueryCacheManager(QueryCacheManagerBase):
    """
    Storing query results in Redis keyed by the hash of the query (cache_key param).
    '{cache_key}' -> query_results

    Also using Redis sorted sets to store the time query results were calculated.

    Sorted sets are keyed by team_id.
    'cache_timestamps:{team_id}' -> '{self.insight_id}:{self.dashboard_id or ''}' -> timestamp (epoch time when calculated)
    """

    def __init__(
        self,
        *,
        team_id: int,
        cache_key: str,
        insight_id: Optional[int] = None,
        dashboard_id: Optional[int] = None,
    ):
        super().__init__(team_id=team_id, cache_key=cache_key, insight_id=insight_id, dashboard_id=dashboard_id)
        self.redis_client = redis.get_client()

    @staticmethod
    def get_stale_insights(*, team_id: int, limit: Optional[int] = None) -> list[str]:
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
        # get least stale insights first
        if limit is not None:
            insights = redis.get_client().zrevrangebyscore(
                f"cache_timestamps:{team_id}",
                min="-inf",
                max=current_time.timestamp(),
                start=0,
                num=limit,
            )
        else:
            insights = redis.get_client().zrevrangebyscore(
                f"cache_timestamps:{team_id}",
                min="-inf",
                max=current_time.timestamp(),
            )
        return [insight.decode("utf-8") for insight in insights]

    @staticmethod
    def clean_up_stale_insights(*, team_id: int, threshold: datetime) -> None:
        """
        Remove all stale insights that are older than the given timestamp.
        """
        redis.get_client().zremrangebyscore(
            f"cache_timestamps:{team_id}",
            "-inf",
            threshold.timestamp(),
        )

    def update_target_age(self, target_age: datetime) -> None:
        if not self.insight_id:
            return

        self.redis_client.zadd(
            f"cache_timestamps:{self.team_id}",
            {self.identifier: target_age.timestamp()},
        )

    def remove_last_refresh(self) -> None:
        if not self.insight_id:
            return

        self.redis_client.zrem(f"cache_timestamps:{self.team_id}", self.identifier)

    def set_cache_data(self, *, response: dict, target_age: Optional[datetime]) -> None:
        fresh_response_serialized = OrjsonJsonSerializer({}).dumps(response)
        cache.set(self.cache_key, fresh_response_serialized, settings.CACHED_RESULTS_TTL)

        if target_age:
            self.update_target_age(target_age)
        else:
            self.remove_last_refresh()

    def get_cache_data(self) -> Optional[dict]:
        cached_response_bytes: Optional[bytes] = get_safe_cache(self.cache_key)
        if not cached_response_bytes:
            return None

        return OrjsonJsonSerializer({}).loads(cached_response_bytes)


# Backward compatibility alias
QueryCacheManager = RedisQueryCacheManager
