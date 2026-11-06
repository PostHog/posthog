from collections.abc import Callable
from typing import TYPE_CHECKING

from prometheus_client import Counter

from posthog.hogql.database.single_flight_cache import SingleFlightTTLCache
from posthog.hogql.database.sources_cache import (
    SOURCES_CACHE_MAX_ENTRY_WEIGHT,
    SOURCES_CACHE_TTL_SECONDS,
    SourcesCacheKey,
    _cache_timer,
    sources_weight,
)

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.hogql.database.database import Database, HogQLDatabaseSources

# A built database bakes in one user's access decisions, so there is one entry per user and team.
# Only editor autocomplete reads these entries: query execution and query printing register
# per-query tables on the database they get, and a shared instance would collect those tables.
DATABASE_CACHE_WEIGHT_BUDGET = 16_384

DATABASE_CACHE_EVENTS = Counter(
    "hogql_database_cache_events_total",
    "HogQL built-database cache lookups for editor autocomplete: hit/miss are lookup outcomes; "
    "oversized counts builds whose catalog was too large to store.",
    labelnames=["result"],
)


@frozen
class DatabaseCacheKey:
    sources_key: SourcesCacheKey
    # id() of the cached sources bundle the database is built from. The entry keeps a reference to
    # that bundle, so the id cannot belong to another object while the entry lives, and a refetched
    # bundle always produces a new key.
    sources_id: int
    user_id: int | None
    access_fingerprint: str
    denied_system_table_names: frozenset[str]
    warehouse_access_control_enabled: bool
    include_flag_evaluations_table: bool
    build_postgres_foreign_keys: bool
    # The build reads these team fields from the request's team, which the sources key does not cover.
    timezone: str | None
    week_start_day: int | None


@frozen
class _CachedDatabase:
    sources: "HogQLDatabaseSources"
    database: "Database"


def _cached_database_weight(entry: _CachedDatabase) -> int:
    return sources_weight(entry.sources)


_database_cache: SingleFlightTTLCache[DatabaseCacheKey, _CachedDatabase] = SingleFlightTTLCache(
    # Matches the sources TTL, because an entry is only valid while its sources bundle is the cached one.
    ttl_seconds=SOURCES_CACHE_TTL_SECONDS,
    weight_budget=DATABASE_CACHE_WEIGHT_BUDGET,
    max_entry_weight=SOURCES_CACHE_MAX_ENTRY_WEIGHT,
    weigh=_cached_database_weight,
    timer=_cache_timer,
    events=DATABASE_CACHE_EVENTS,
)


def get_or_build_database(
    key: DatabaseCacheKey, sources: "HogQLDatabaseSources", build: Callable[[], "Database"]
) -> "Database":
    if key.sources_id != id(sources):
        raise ValueError("DatabaseCacheKey.sources_id must be the id of the sources bundle passed in")
    return _database_cache.get_or_compute(key, lambda: _CachedDatabase(sources=sources, database=build())).database


def clear_database_cache() -> None:
    _database_cache.clear()
