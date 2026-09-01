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
SOURCES_CACHE_MAX_ENTRIES = 128

SOURCES_CACHE_EVENTS = Counter(
    "hogql_database_sources_cache_events_total",
    "HogQL database sources-cache lookups",
    labelnames=["result"],  # "hit" | "miss" | "bypass"
)

# Indirection so tests can advance the cache clock without waiting out the TTL.
_time_source: Callable[[], float] = time.monotonic


def _cache_timer() -> float:
    return _time_source()


@frozen
class SourcesCacheKey:
    team_id: int
    user_id: int | None
    connection_id: str | None
    modifiers_fingerprint: str
    bypass_warehouse_access_control: bool


_sources_cache: TTLCache["SourcesCacheKey", "HogQLDatabaseSources"] = TTLCache(
    maxsize=SOURCES_CACHE_MAX_ENTRIES, ttl=SOURCES_CACHE_TTL_SECONDS, timer=_cache_timer
)
# cachetools caches are not thread-safe; the lock guards threaded WSGI/Celery workers.
_sources_cache_lock = threading.Lock()


def modifiers_fingerprint(modifiers: "HogQLQueryModifiers") -> str:
    return hashlib.sha256(modifiers.model_dump_json().encode()).hexdigest()


def get_or_fetch_sources(key: SourcesCacheKey, fetch: Callable[[], "HogQLDatabaseSources"]) -> "HogQLDatabaseSources":
    with _sources_cache_lock:
        cached = _sources_cache.get(key)
    if cached is not None:
        SOURCES_CACHE_EVENTS.labels(result="hit").inc()
        return cached
    SOURCES_CACHE_EVENTS.labels(result="miss").inc()
    sources = fetch()
    with _sources_cache_lock:
        _sources_cache[key] = sources
    return sources


def clear_sources_cache() -> None:
    with _sources_cache_lock:
        _sources_cache.clear()
