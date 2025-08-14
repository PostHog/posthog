from typing import Optional, TYPE_CHECKING

from posthog.hogql_queries.query_cache_base import QueryCacheManagerBase
from posthog.hogql_queries.query_cache_dual import DualCacheManager
from posthog.hogql_queries.legacy_compatibility.feature_flag import query_cache_use_s3
from posthog.models import Team

if TYPE_CHECKING:
    from posthog.models import User


def get_query_cache_manager(
    *,
    team: Team,
    cache_key: str,
    insight_id: Optional[int] = None,
    dashboard_id: Optional[int] = None,
    user: Optional["User"] = None,
) -> QueryCacheManagerBase:
    """
    Factory function to create the DualCacheManager.

    Mode 1 (s3_enabled=True): Only use S3 cache
    Mode 2 (s3_enabled=False): Write to both Redis and S3, but always read from S3

    Args:
        team: The team to get cache manager for
        cache_key: The cache key to use
        insight_id: Optional insight ID
        dashboard_id: Optional dashboard ID
        user: Optional user for user-specific feature flag evaluation
    """
    s3_enabled = query_cache_use_s3(team, user=user)

    return DualCacheManager(
        team_id=team.pk,
        cache_key=cache_key,
        insight_id=insight_id,
        dashboard_id=dashboard_id,
        s3_enabled=s3_enabled,
    )
