from datetime import datetime, UTC
from typing import Optional

from django.conf import settings
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
        insight_id: Optional[int] = None,
        dashboard_id: Optional[int] = None,
    ):
        self.redis_client = redis.get_client()
        self.team_id = team_id
        self.cache_key = cache_key
        self.insight_id = insight_id
        self.dashboard_id = dashboard_id

    @staticmethod
    def get_stale_insights(*, team_id: int, limit: Optional[int] = None) -> list[str]:
        """
        Use redis sorted set to get stale insights. We sort by the timestamp and get the insights that are
        stale compared to the current time. We start with the least stale insights.
        """
        current_time = datetime.now(UTC)
        insights = redis.get_client().zrangebyscore(
            f"cache_timestamps:{team_id}",
            "-inf",
            current_time.timestamp(),
        )
        insights = [insight.decode("utf-8") for insight in insights]
        if limit:
            insights = insights[-limit:]
        return insights

    def update_last_refresh(self, target_age: datetime) -> None:
        if not self.insight_id:
            return

        identifier = f"{self.insight_id}:{self.dashboard_id or ''}"
        self.redis_client.zadd(f"cache_timestamps:{self.team_id}", {identifier: target_age.timestamp()})

    def set_cache_data(self, *, response: dict) -> None:
        fresh_response_serialized = OrjsonJsonSerializer({}).dumps(response)
        cache.set(self.cache_key, fresh_response_serialized, settings.CACHED_RESULTS_TTL)

        if response.get("cache_target_age"):
            self.update_last_refresh(response["cache_target_age"])

    def get_cache_data(self) -> Optional[dict]:
        cached_response_bytes: Optional[bytes] = get_safe_cache(self.cache_key)
        if not cached_response_bytes:
            return None

        return OrjsonJsonSerializer({}).loads(cached_response_bytes)
