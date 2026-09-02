import time
import hashlib
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from cachetools import TTLCache
from prometheus_client import Counter

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.schema import HogQLQueryModifiers

    from posthog.hogql.database.database import HogQLDatabaseSources

# Editor-assist queries (autocomplete, metadata) fire on every keystroke and each one pays the
# full Postgres + feature-flag cost of Database._fetch_sources. A short TTL bounds staleness:
# a just-created view appears in suggestions within this window, while query execution always
# builds fresh sources and is never affected.
SOURCES_CACHE_TTL_SECONDS = 60

# Entries hold a team's warehouse catalog (ORM rows), whose size varies by orders of magnitude
# across teams, so the cache is bounded by total row weight rather than entry count. Teams whose
# catalog exceeds the per-entry limit skip the cache instead of evicting everyone else.
SOURCES_CACHE_WEIGHT_BUDGET = 16_384
SOURCES_CACHE_MAX_ENTRY_WEIGHT = 4_096

SOURCES_CACHE_EVENTS = Counter(
    "hogql_database_sources_cache_events_total",
    "HogQL database sources-cache lookups: hit/miss/bypass are lookup outcomes; oversized counts "
    "fetches whose result was too large to store.",
    labelnames=["result"],
)

# Indirection so tests can advance the cache clock without waiting out the TTL.
_time_source: Callable[[], float] = time.monotonic


def _cache_timer() -> float:
    return _time_source()


@frozen
class SourcesCacheKey:
    team_id: int
    connection_id: str | None
    modifiers_fingerprint: str
    bypass_warehouse_access_control: bool


def sources_weight(sources: "HogQLDatabaseSources") -> int:
    """Cache weight of a sources bundle: the number of ORM rows it retains."""
    return 1 + sum(
        (
            len(sources.group_types),
            len(sources.saved_queries),
            len(sources.endpoint_saved_queries),
            len(sources.revenue_views),
            len(sources.warehouse_tables),
            len(sources.data_warehouse_joins),
            len(sources.data_warehouse_expressions),
            len(sources.event_modifier_saved_queries),
            len(sources.virtual_schemas),
        )
    )


_sources_cache: TTLCache["SourcesCacheKey", "HogQLDatabaseSources"] = TTLCache(
    maxsize=SOURCES_CACHE_WEIGHT_BUDGET,
    ttl=SOURCES_CACHE_TTL_SECONDS,
    timer=_cache_timer,
    getsizeof=sources_weight,
)
# cachetools caches are not thread-safe; the lock guards threaded WSGI/Celery workers.
_sources_cache_lock = threading.Lock()
# Per-key single-flight locks: concurrent misses for one key wait for a single fetch instead of
# each running the full Postgres fetch. Entries are removed once their fetch settles.
_inflight_locks: dict["SourcesCacheKey", threading.Lock] = {}


def modifiers_fingerprint(modifiers: "HogQLQueryModifiers") -> str:
    return hashlib.sha256(modifiers.model_dump_json().encode()).hexdigest()


def get_or_fetch_sources(key: SourcesCacheKey, fetch: Callable[[], "HogQLDatabaseSources"]) -> "HogQLDatabaseSources":
    key_lock = threading.Lock()
    with _sources_cache_lock:
        cached = _sources_cache.get(key)
        if cached is None:
            key_lock = _inflight_locks.setdefault(key, key_lock)
    if cached is not None:
        SOURCES_CACHE_EVENTS.labels(result="hit").inc()
        return cached

    # The fetch runs outside the global cache lock so one slow team cannot stall every other
    # team's lookups; the per-key lock still collapses concurrent same-key misses to one fetch.
    with key_lock:
        with _sources_cache_lock:
            cached = _sources_cache.get(key)
        if cached is not None:
            SOURCES_CACHE_EVENTS.labels(result="hit").inc()
            return cached

        SOURCES_CACHE_EVENTS.labels(result="miss").inc()
        try:
            sources = fetch()
        finally:
            with _sources_cache_lock:
                _inflight_locks.pop(key, None)

        if sources_weight(sources) > SOURCES_CACHE_MAX_ENTRY_WEIGHT:
            SOURCES_CACHE_EVENTS.labels(result="oversized").inc()
            return sources
        with _sources_cache_lock:
            _sources_cache[key] = sources
        return sources


def clear_sources_cache() -> None:
    with _sources_cache_lock:
        _sources_cache.clear()
        _inflight_locks.clear()
