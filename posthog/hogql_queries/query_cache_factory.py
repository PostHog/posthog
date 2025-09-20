from typing import Optional

from posthog.hogql_queries.query_cache import DjangoCacheQueryCacheManager
from posthog.hogql_queries.query_cache_base import QueryCacheManagerBase
from posthog.models import Team


def get_query_cache_manager(
    *,
    team: Team,
    cache_key: str,
    insight_id: Optional[int] = None,
    dashboard_id: Optional[int] = None,
) -> QueryCacheManagerBase:
    return DjangoCacheQueryCacheManager(
        team_id=team.pk,
        cache_key=cache_key,
        insight_id=insight_id,
        dashboard_id=dashboard_id,
    )
