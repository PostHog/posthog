from datetime import datetime
from typing import Optional

from django.core.cache import cache

from posthog import redis
from posthog.cache_utils import OrjsonJsonSerializer
from posthog.utils import get_safe_cache


class QueryCacheManager:
    def __init__(
        self,
        *,
        team_id: int,
        cache_key: str,
        cache_ttl: float,
        insight_id: Optional[int] = None,
        dashboard_id: Optional[int] = None,
    ):
        self.redis_client = redis.get_client()
        self.team_id = team_id
        self.cache_key = cache_key
        self.cache_ttl = cache_ttl
        self.insight_id = insight_id
        self.dashboard_id = dashboard_id

    def update_last_refresh(self, timestamp: float) -> None:
        if not self.insight_id:
            return

        identifier = f"{self.insight_id}:{self.dashboard_id or ''}"
        self.redis_client.zadd(f"cache_timestamps:{self.team_id}", {identifier: timestamp})

    def get_stale_insights(self, *, team_id: int, current_time: float, limit: Optional[int] = None) -> list[str]:
        insights = self.redis_client.zrangebyscore(f"cache_timestamps:{team_id}", "-inf", current_time)
        if limit:
            insights = insights[-limit:]
        return insights

    def set_cache_data(self, *, response: dict, cache_target_age: datetime) -> None:
        fresh_response_serialized = OrjsonJsonSerializer({}).dumps(response)
        cache.set(self.cache_key, fresh_response_serialized, self.cache_ttl)

        self.update_last_refresh(cache_target_age.timestamp())

    def get_cache_data(self) -> Optional[dict]:
        cached_response_bytes: Optional[bytes] = get_safe_cache(self.cache_key)
        if not cached_response_bytes:
            return None

        return OrjsonJsonSerializer({}).loads(cached_response_bytes)


class QueryExecutionManager:
    # can be injected into query runner run method

    def __init__(self):
        pass
