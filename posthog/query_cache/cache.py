from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from django.conf import settings

import structlog

from posthog.cache_utils import OrjsonJsonSerializer
from posthog.query_cache.failures import Budget, FailureKind, QueryFailureCache, QueryFailureRecord
from posthog.query_cache.freshness_index import remove_last_refresh, update_target_age
from posthog.query_cache.metrics import count_cache_write_data
from posthog.query_cache.results import EntryFreshness, fetch_entry, fetch_entry_freshness
from posthog.query_cache.serialization import CachedEntry, encode_split_cached_response
from posthog.query_cache.size_tracker import TeamCacheSizeTracker
from posthog.query_cache.storage import encode_inline_value, schedule_upload_for_pointer

logger = structlog.get_logger(__name__)


def _last_refresh_iso(response: dict) -> Optional[str]:
    value = response.get("last_refresh")
    if isinstance(value, datetime):
        return value.isoformat()
    return value if isinstance(value, str) else None


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

    def freshness(self) -> Optional[EntryFreshness]:
        """Existence and last_refresh of the entry from Redis alone, without resolving S3 blobs."""
        return fetch_entry_freshness(self.cache_key, self.team_id)

    def open_failure(self) -> Optional[QueryFailureRecord]:
        """The open breaker record alone, for paths that skip the result cache entirely."""
        return QueryFailureCache(self.cache_key).get_open()

    def record_failure(self, kind: FailureKind, detail: str, *, budget: Budget) -> Optional[QueryFailureRecord]:
        return QueryFailureCache(self.cache_key).record_failure(kind, detail, budget=budget)

    def clear_failure(self) -> None:
        QueryFailureCache(self.cache_key).clear()

    def store_result(self, *, response: dict, target_age: Optional[datetime]) -> None:
        if isinstance(response.get("results"), list):
            # Split format keeps `results` as its own JSON segment so cache hits can skip
            # parsing it (see CachedEntry). Pods that predate the format treat split entries
            # as cache misses and recompute once during a rolling deploy. Accepted: deploys
            # are quick.
            fresh_response_serialized = encode_split_cached_response(response)
        else:
            fresh_response_serialized = OrjsonJsonSerializer({}).dumps(response)
        data_size = len(fresh_response_serialized)

        # The tracker budgets the bytes actually stored in Redis (compressed blob or pointer);
        # the write metrics below keep counting the uncompressed payload. Caching is an
        # optimization: the query has already run, so a failure in this block must not fail
        # the response.
        try:
            storage_bytes = encode_inline_value(fresh_response_serialized)
            tracker = TeamCacheSizeTracker(self.team_id)
            tracker.set(self.cache_key, storage_bytes, settings.CACHED_RESULTS_TTL)
            # The S3 upload runs on a background thread after the inline write: the fresh
            # result is already cached, so the requester never waits on S3, and a failed or
            # skipped upload leaves the valid inline entry in place. The swap only lands while
            # the entry still holds this store's bytes, so an upload that finishes after a
            # newer store wrote the key cannot put its older result back.
            schedule_upload_for_pointer(
                team_id=self.team_id,
                cache_key=self.cache_key,
                inline_value=storage_bytes,
                last_refresh=_last_refresh_iso(response),
                swap=lambda pointer: tracker.replace_value(
                    self.cache_key, pointer, settings.CACHED_RESULTS_TTL, expected=storage_bytes
                ),
            )
        except Exception:
            logger.exception("query_cache_store_result_failed", team_id=self.team_id, cache_key=self.cache_key)
            return

        if target_age:
            update_target_age(
                team_id=self.team_id,
                insight_id=self.insight_id,
                dashboard_id=self.dashboard_id,
                target_age=target_age,
            )
        else:
            remove_last_refresh(team_id=self.team_id, insight_id=self.insight_id, dashboard_id=self.dashboard_id)

        count_cache_write_data(data_size)
