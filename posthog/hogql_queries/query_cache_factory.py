from typing import Optional

from django.conf import settings

from posthog.hogql_queries.query_cache_base import QueryCacheManagerBase
from posthog.hogql_queries.query_cache import RedisQueryCacheManager
from posthog.hogql_queries.query_cache_s3 import S3QueryCacheManager
from posthog.hogql_queries.legacy_compatibility.feature_flag import query_cache_use_s3
from posthog.models import Team


def get_query_cache_manager(
    *,
    team_id: int,
    cache_key: str,
    insight_id: Optional[int] = None,
    dashboard_id: Optional[int] = None,
) -> QueryCacheManagerBase:
    """
    Factory function to create the appropriate query cache manager based on feature flags.

    Uses S3QueryCacheManager if the 'query-cache-use-s3' feature flag is enabled for the team,
    otherwise uses RedisQueryCacheManager.

    Falls back to settings.QUERY_CACHE_BACKEND if team cannot be determined.
    """
    try:
        team = Team.objects.get(id=team_id)
        use_s3 = query_cache_use_s3(team)
    except Team.DoesNotExist:
        # Fallback to settings if team doesn't exist
        use_s3 = getattr(settings, "QUERY_CACHE_BACKEND", "redis") == "s3"

    if use_s3:
        return S3QueryCacheManager(
            team_id=team_id,
            cache_key=cache_key,
            insight_id=insight_id,
            dashboard_id=dashboard_id,
        )
    else:
        return RedisQueryCacheManager(
            team_id=team_id,
            cache_key=cache_key,
            insight_id=insight_id,
            dashboard_id=dashboard_id,
        )
