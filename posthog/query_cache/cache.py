from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from django.conf import settings

from posthog.cache_utils import OrjsonJsonSerializer
from posthog.query_cache.failures import FailureKind, QueryFailureCache, QueryFailureRecord
from posthog.query_cache.freshness_index import remove_last_refresh, update_target_age
from posthog.query_cache.metrics import count_cache_write_data
from posthog.query_cache.results import fetch_entry
from posthog.query_cache.serialization import CachedEntry, encode_split_cached_response
from posthog.query_cache.size_tracker import TeamCacheSizeTracker


@dataclass(frozen=True)
class CacheLookup:
    """Everything the cache knows about a cache key: the stored entry and any open failure record."""

    entry: Optional[CachedEntry]
    failure: Optional[QueryFailureRecord] = None


class QueryCache:
    """Facade over query result cache storage: blob store, wire format, per-team size limits,
    the freshness index, and the failure circuit breaker. Code outside posthog/query_cache
    goes through this class."""

    def __init__(
        self,
        *,
        team_id: int,
        cache_key: str,
        insight_id: Optional[int] = None,
        dashboard_id: Optional[int] = None,
    ) -> None:
        self.team_id = team_id
        self.cache_key = cache_key
        self.insight_id = insight_id
        self.dashboard_id = dashboard_id

    def lookup(self, *, include_failure: bool = False) -> CacheLookup:
        # The failure read is opt-in so callers that never consult the breaker (and the
        # feature-flag-off path) don't pay an extra cache roundtrip per query.
        failure = QueryFailureCache(self.cache_key).get_open() if include_failure else None
        return CacheLookup(entry=fetch_entry(self.cache_key, self.team_id), failure=failure)

    def open_failure(self) -> Optional[QueryFailureRecord]:
        """The open breaker record alone, for paths that skip the result cache entirely."""
        return QueryFailureCache(self.cache_key).get_open()

    def record_failure(self, kind: FailureKind, detail: str, *, scope: str) -> Optional[QueryFailureRecord]:
        return QueryFailureCache(self.cache_key).record_failure(kind, detail, scope=scope)

    def clear_failure(self) -> None:
        QueryFailureCache(self.cache_key).clear()

    def store_result(self, *, response: dict, target_age: Optional[datetime]) -> None:
        if isinstance(response.get("results"), list):
            # Split format keeps `results` as its own JSON segment so cache hits can skip
            # parsing it — see CachedEntry. Pods that predate this
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
            update_target_age(
                team_id=self.team_id,
                insight_id=self.insight_id,
                dashboard_id=self.dashboard_id,
                target_age=target_age,
            )
        else:
            remove_last_refresh(team_id=self.team_id, insight_id=self.insight_id, dashboard_id=self.dashboard_id)

        count_cache_write_data(self.team_id, data_size)
