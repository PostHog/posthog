from datetime import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from posthog.caching.fetch_from_cache import SplitCachedResponse

from django.conf import settings

import structlog

from posthog.cache_utils import OrjsonJsonSerializer
from posthog.hogql_queries.query_cache_base import QueryCacheManagerBase
from posthog.query_cache.metrics import count_cache_write_data
from posthog.query_cache.size_tracker import TeamCacheSizeTracker

logger = structlog.get_logger(__name__)


class DjangoCacheQueryCacheManager(QueryCacheManagerBase):
    """
    Storing query results in Django cache (typically Redis) keyed by the hash of the query (cache_key param).
    '{cache_key}' -> query_results

    Uses Redis sorted sets (from base class) to store the time query results were calculated.
    'cache_timestamps:{team_id}' -> '{self.insight_id}:{self.dashboard_id or ''}' -> timestamp (epoch time when calculated)
    """

    def set_cache_data(self, *, response: dict, target_age: Optional[datetime]) -> None:
        from posthog.caching.fetch_from_cache import encode_split_cached_response

        if isinstance(response.get("results"), list):
            # Split format keeps `results` as its own JSON segment so cache hits can skip
            # parsing it — see fetch_from_cache.SplitCachedResponse. Pods that predate this
            # format treat split entries as cache misses and recompute, so entries written
            # during a rolling deploy may be recomputed once — accepted, deploys are quick.
            fresh_response_serialized = encode_split_cached_response(response)
        else:
            fresh_response_serialized = OrjsonJsonSerializer({}).dumps(response)
        data_size = len(fresh_response_serialized)

        # Set cache with per-team size limit enforcement
        tracker = TeamCacheSizeTracker(self.team_id)
        tracker.set(self.cache_key, fresh_response_serialized, data_size, settings.CACHED_RESULTS_TTL)

        if target_age:
            self.update_target_age(target_age)
        else:
            self.remove_last_refresh()

        # Track cache write metrics
        count_cache_write_data(self.team_id, data_size)

    def get_cache_data(self) -> Optional[dict]:
        from posthog.caching.fetch_from_cache import fetch_cached_response_by_key

        return fetch_cached_response_by_key(self.cache_key, self.team_id)

    def get_cache_data_split(self) -> Optional["SplitCachedResponse"]:
        from posthog.caching.fetch_from_cache import fetch_split_cached_response_by_key

        return fetch_split_cached_response_by_key(self.cache_key, self.team_id)
