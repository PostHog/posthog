from datetime import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from posthog.caching.fetch_from_cache import SplitCachedResponse

from posthog.hogql_queries.query_cache_base import QueryCacheManagerBase
from posthog.query_cache.cache import QueryCache


class DjangoCacheQueryCacheManager(QueryCacheManagerBase):
    """
    Storing query results in Django cache (typically Redis) keyed by the hash of the query (cache_key param).
    '{cache_key}' -> query_results

    Uses Redis sorted sets (from base class) to store the time query results were calculated.
    'cache_timestamps:{team_id}' -> '{self.insight_id}:{self.dashboard_id or ''}' -> timestamp (epoch time when calculated)
    """

    def _facade(self) -> QueryCache:
        return QueryCache(
            team_id=self.team_id,
            cache_key=self.cache_key,
            insight_id=self.insight_id,
            dashboard_id=self.dashboard_id,
        )

    def set_cache_data(self, *, response: dict, target_age: Optional[datetime]) -> None:
        self._facade().store_result(response=response, target_age=target_age)

    def get_cache_data(self) -> Optional[dict]:
        entry = self._facade().lookup().entry
        return entry.as_full_response() if entry else None

    def get_cache_data_split(self) -> Optional["SplitCachedResponse"]:
        return self._facade().lookup().entry
