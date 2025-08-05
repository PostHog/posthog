from typing import Optional

from django.conf import settings

from posthog.hogql_queries.query_cache_base import QueryCacheManagerBase
from posthog.hogql_queries.query_cache import RedisQueryCacheManager
from posthog.hogql_queries.query_cache_s3 import S3QueryCacheManager


def get_query_cache_manager(
    *,
    team_id: int,
    cache_key: str,
    insight_id: Optional[int] = None,
    dashboard_id: Optional[int] = None,
) -> QueryCacheManagerBase:
    """
    Factory function to create the appropriate query cache manager based on settings.

    Returns RedisQueryCacheManager by default, or S3QueryCacheManager if configured.
    """
    cache_backend = getattr(settings, "QUERY_CACHE_BACKEND", "redis")

    if cache_backend == "s3":
        return S3QueryCacheManager(
            team_id=team_id,
            cache_key=cache_key,
            insight_id=insight_id,
            dashboard_id=dashboard_id,
        )
    else:
        # Default to Redis
        return RedisQueryCacheManager(
            team_id=team_id,
            cache_key=cache_key,
            insight_id=insight_id,
            dashboard_id=dashboard_id,
        )
