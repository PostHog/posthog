from typing import Optional, TYPE_CHECKING


from posthog.hogql_queries.query_cache_base import QueryCacheManagerBase
from posthog.hogql_queries.query_cache import DjangoCacheQueryCacheManager
from posthog.hogql_queries.query_cache_s3 import S3QueryCacheManager
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
    Factory function to create the appropriate query cache manager based on feature flags.

    Uses S3QueryCacheManager if the 'query-cache-use-s3' feature flag is enabled for the team/user,
    otherwise uses DjangoCacheQueryCacheManager.

    Args:
        team: The team to get cache manager for
        cache_key: The cache key to use
        insight_id: Optional insight ID
        dashboard_id: Optional dashboard ID
        user: Optional user for user-specific feature flag evaluation
    """
    use_s3 = query_cache_use_s3(team, user=user)

    if use_s3:
        return S3QueryCacheManager(
            team_id=team.pk,
            cache_key=cache_key,
            insight_id=insight_id,
            dashboard_id=dashboard_id,
        )
    else:
        return DjangoCacheQueryCacheManager(
            team_id=team.pk,
            cache_key=cache_key,
            insight_id=insight_id,
            dashboard_id=dashboard_id,
        )
