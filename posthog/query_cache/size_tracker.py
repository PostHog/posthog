import time
from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.db import DatabaseError

import structlog
from prometheus_client import Counter, Histogram
from redis import Redis, RedisCluster

from posthog.cache_utils import cache_for
from posthog.dataclasses import frozen
from posthog.query_cache import storage

logger = structlog.get_logger(__name__)


@frozen
class TeamCacheTotals:
    total_bytes: int
    entry_count: int


CACHE_EVICTION_COUNTER = Counter(
    "query_cache_size_limit_evictions_total",
    "Cache entries evicted due to per-team size limits",
)

CACHE_EVICTION_BYTES_COUNTER = Counter(
    "query_cache_size_limit_evicted_bytes_total",
    "Bytes evicted due to per-team size limits",
)

CACHE_EVICTION_AGE_HISTOGRAM = Histogram(
    "query_cache_eviction_age_seconds",
    "Age of cache entries at eviction time (seconds since write)",
    buckets=[
        1800,  # 30 min
        3600,  # 1 hour
        14400,  # 4 hours
        43200,  # 12 hours
        86400,  # 1 day
        172800,  # 2 days
        345600,  # 4 days
        604800,  # 7 days
        float("inf"),
    ],
)

CACHE_SIZE_HISTOGRAM = Histogram(
    "query_cache_team_size_bytes",
    "Distribution of per-team cache sizes in bytes",
    buckets=[
        1_000_000,  # 1MB
        10_000_000,  # 10MB
        50_000_000,  # 50MB
        100_000_000,  # 100MB
        250_000_000,  # 250MB
        500_000_000,  # 500MB
        750_000_000,  # 750MB
        1_000_000_000,  # 1GB
        1_500_000_000,
        2_000_000_000,
        2_500_000_000,
        3_000_000_000,
        3_500_000_000,
        4_000_000_000,
        5_000_000_000,
        float("inf"),
    ],
)

# Lua script for atomic cache write tracking
# Handles overwrite detection and counter updates in a single atomic operation
TRACK_CACHE_WRITE_SCRIPT = """
local entries_key = KEYS[1]
local sizes_key = KEYS[2]
local total_key = KEYS[3]

local cache_key = ARGV[1]
local size_bytes = tonumber(ARGV[2])
local timestamp = tonumber(ARGV[3])
local tracking_ttl = tonumber(ARGV[4])

-- Atomically handle overwrite: only decrement if key exists
local old_size = redis.call('HGET', sizes_key, cache_key)
if old_size then
    redis.call('INCRBY', total_key, -tonumber(old_size))
end

-- Update tracking
redis.call('ZADD', entries_key, timestamp, cache_key)
redis.call('HSET', sizes_key, cache_key, size_bytes)
redis.call('INCRBY', total_key, size_bytes)

-- Refresh TTLs
redis.call('EXPIRE', entries_key, tracking_ttl)
redis.call('EXPIRE', sizes_key, tracking_ttl)
redis.call('EXPIRE', total_key, tracking_ttl)

return {redis.call('GET', total_key), redis.call('ZCARD', entries_key)}
"""

# Lua script for the entry write: store the new value and hand back the value it replaced,
# but only when that value is an S3 pointer record (ARGV[3] is the pointer magic). Capturing
# atomically with the write guarantees a returned pointer is dereferenced, so its blob is
# safe to delete; filtering server-side keeps multi-megabyte inline blobs off the wire.
SET_ENTRY_RETURNING_OLD_POINTER_SCRIPT = """
local old = redis.call('GET', KEYS[1])
redis.call('SET', KEYS[1], ARGV[1], 'EX', tonumber(ARGV[2]))
if old and string.sub(old, 1, string.len(ARGV[3])) == ARGV[3] then
    return old
end
"""

# Lua script for eviction: delete the entry and report what was there. Returns nil when the
# key was already gone (TTL expiry), the old value when it was an S3 pointer (ARGV[1] is the
# pointer magic), and 1 otherwise, again keeping inline blobs off the wire.
DELETE_ENTRY_RETURNING_OLD_POINTER_SCRIPT = """
local old = redis.call('GET', KEYS[1])
if not old then
    return nil
end
redis.call('DEL', KEYS[1])
if string.sub(old, 1, string.len(ARGV[1])) == ARGV[1] then
    return old
end
return 1
"""

# Lua script for the pointer swap: replace the entry only while it still holds the exact bytes
# the caller wrote, so a swap that lost a race to a newer write skips instead of clobbering it.
# Compares the full expected value rather than a redis.sha1hex digest because fakeredis's Lua
# runtime, which the tests run on, does not implement sha1hex.
# The already-swapped check makes the script idempotent: the cluster client retries EVALSHA
# when a reply is lost, and a retry after the swap landed must read as swapped, not as
# superseded, because the superseded path deletes the blob the entry now points at. Pointer
# records embed a per-upload uuid, so only this caller's own swap can have written ARGV[2].
REPLACE_IF_UNCHANGED_SCRIPT = """
local current = redis.call('GET', KEYS[1])
if current == ARGV[2] then
    return 2
end
if current ~= ARGV[1] then
    return 0
end
redis.call('SET', KEYS[1], ARGV[2], 'EX', tonumber(ARGV[3]))
return 1
"""

# Lua script for atomic and idempotent tracking removal
# Only decrements if key exists in hash, preventing double-decrement races
REMOVE_TRACKING_SCRIPT = """
local sizes_key = KEYS[1]
local total_key = KEYS[2]
local cache_key = ARGV[1]

-- Only decrement if key exists in hash (idempotent)
local size = redis.call('HGET', sizes_key, cache_key)
if size then
    redis.call('HDEL', sizes_key, cache_key)
    redis.call('INCRBY', total_key, -tonumber(size))
    return tonumber(size)
end
return 0
"""


@cache_for(timedelta(seconds=60))
def get_team_cache_limit(team_id: int) -> int:
    """Get cache limit for team, checking for per-team override in extra_settings."""
    from posthog.models import Team

    try:
        team = Team.objects.only("extra_settings").get(pk=team_id)
        if team.extra_settings and "cache_size_limit_bytes" in team.extra_settings:
            return int(team.extra_settings["cache_size_limit_bytes"])
    except Team.DoesNotExist:
        pass
    except DatabaseError:
        # This lookup only reads an optional override, so a struggling Postgres must not fail
        # the query whose result we're about to cache.
        logger.warning("query_cache_team_limit_lookup_failed", team_id=team_id, exc_info=True)
    return settings.TEAM_CACHE_SIZE_LIMIT_BYTES


class TeamCacheSizeTracker:
    """
    Tracks cache size per team using Redis data structures.

    Redis keys used:
    - posthog:cache_sizes:{team_id} - Sorted set: member=cache_key, score=timestamp (for LRU ordering)
    - posthog:cache_entry_sizes:{team_id} - Hash: field=cache_key, value=size (for O(1) size lookup)
    - posthog:cache_total:{team_id} - String counter: total bytes (for O(1) total size lookup)
    """

    def __init__(
        self,
        team_id: int,
        redis_client: Redis | RedisCluster | None = None,
    ):
        self.team_id = team_id
        self.redis_client: Redis | RedisCluster = (
            redis_client if redis_client is not None else storage.query_cache_raw_client()
        )
        self.entries_key = f"posthog:cache_sizes:{{{team_id}}}"
        self.sizes_key = f"posthog:cache_entry_sizes:{{{team_id}}}"
        self.total_key = f"posthog:cache_total:{{{team_id}}}"

        # redis-py's stubs omit register_script on RedisCluster; the runtime supports it.
        self._track_write_script = self.redis_client.register_script(TRACK_CACHE_WRITE_SCRIPT)  # type: ignore[union-attr]
        self._set_entry_script = self.redis_client.register_script(SET_ENTRY_RETURNING_OLD_POINTER_SCRIPT)  # type: ignore[union-attr]
        self._delete_entry_script = self.redis_client.register_script(DELETE_ENTRY_RETURNING_OLD_POINTER_SCRIPT)  # type: ignore[union-attr]
        self._replace_if_unchanged_script = self.redis_client.register_script(REPLACE_IF_UNCHANGED_SCRIPT)  # type: ignore[union-attr]
        self._remove_tracking_script = self.redis_client.register_script(REMOVE_TRACKING_SCRIPT)  # type: ignore[union-attr]

    def set(self, cache_key: str, data: bytes, ttl: int) -> list[str]:
        """
        Set cache data with size limit enforcement.
        Returns list of evicted keys.

        Note: There's a race condition where concurrent sets for the same team can
        temporarily exceed the limit. This is acceptable because the next write will
        trigger eviction and bring the size back under limit.
        """
        data_size = len(data)
        limit = get_team_cache_limit(self.team_id)
        evicted: list[str] = []
        size_before = self.get_total_size()

        # Race condition: between this check and the write below, other requests may write,
        # causing the total to exceed the limit. This is corrected on subsequent writes.
        if size_before + data_size > limit:
            evicted = self.evict_until_under_limit(limit, data_size)

        old_pointer = self._set_entry_script(
            keys=[storage.entry_redis_key(cache_key)],
            args=[data, ttl, storage.S3_POINTER_MAGIC],
        )
        storage.schedule_blob_delete(old_pointer, team_id=self.team_id, cache_key=cache_key, trigger="replaced")
        totals = self.track_cache_write(cache_key, data_size)

        CACHE_SIZE_HISTOGRAM.observe(totals.total_bytes)

        logger.info(
            "query_cache_write",
            team_id=self.team_id,
            entry_size=data_size,
            size_before=size_before,
            size_after=totals.total_bytes,
            limit=limit,
            count_after=totals.entry_count,
            evicted_count=len(evicted),
        )

        return evicted

    def replace_value(self, cache_key: str, data: bytes, ttl: int, *, expected: bytes) -> bool:
        """Swap an entry's stored bytes for `data` only while it still holds `expected`,
        updating size accounting on success; returns whether the swap landed. Skips set()'s
        limit check and logging: for the pointer swap, where the new value only ever shrinks
        usage, and a store that landed mid-upload must not be replaced by an older upload's
        pointer. Also runs on upload worker threads, so it must stay free of Django ORM calls.
        """
        swapped = self._replace_if_unchanged_script(
            keys=[storage.entry_redis_key(cache_key)],
            args=[expected, data, ttl],
        )
        if not swapped:
            return False
        self.track_cache_write(cache_key, len(data))
        return True

    def track_cache_write(self, cache_key: str, size_bytes: int) -> "TeamCacheTotals":
        """Track a cache write with its size, returning the team's totals after it. Atomic via Lua script."""
        tracking_ttl = settings.CACHED_RESULTS_TTL + 86400
        total_bytes, entry_count = self._track_write_script(
            keys=[self.entries_key, self.sizes_key, self.total_key],
            args=[cache_key, size_bytes, time.time(), tracking_ttl],
        )
        return TeamCacheTotals(total_bytes=int(total_bytes), entry_count=int(entry_count))

    def get_total_size(self) -> int:
        return int(self.redis_client.get(self.total_key) or 0)

    def evict_until_under_limit(self, limit_bytes: int, new_entry_size: int) -> list[str]:
        """
        Evict oldest entries (LRU) until total + new_entry_size <= limit.
        Uses ZPOPMIN for atomic dequeue - prevents double-eviction races.
        Lazy cleanup happens here - removes tracking for TTL-expired keys.
        """
        evicted_keys: list[str] = []
        current_size = self.get_total_size()

        while current_size + new_entry_size > limit_bytes:
            result = self.redis_client.zpopmin(self.entries_key, 1)
            if not result:
                break

            cache_key, write_timestamp = result[0]
            if isinstance(cache_key, bytes):
                cache_key = cache_key.decode()

            old_value = self._delete_entry_script(
                keys=[storage.entry_redis_key(cache_key)],
                args=[storage.S3_POINTER_MAGIC],
            )
            if old_value is None:
                # Already expired via TTL, just clean up tracking
                removed_size = self._remove_tracking(cache_key)
                current_size -= removed_size
                continue

            # Tracking removal stays immediately after the entry delete: a concurrent set() of
            # the same key landing between them loses its accounting (pre-existing, accepted,
            # self-heals on the key's next write), so the enqueue must not widen that gap.
            removed_size = self._remove_tracking(cache_key)
            storage.schedule_blob_delete(old_value, team_id=self.team_id, cache_key=cache_key, trigger="evicted")

            current_size -= removed_size
            evicted_keys.append(cache_key)

            CACHE_EVICTION_COUNTER.inc()
            CACHE_EVICTION_BYTES_COUNTER.inc(removed_size)
            eviction_age = time.time() - float(write_timestamp)
            CACHE_EVICTION_AGE_HISTOGRAM.observe(eviction_age)

        return evicted_keys

    def purge(self) -> None:
        """Delete all tracking data for this team."""
        self.redis_client.delete(self.entries_key, self.sizes_key, self.total_key)

    def _get_key_size(self, cache_key: str) -> Optional[int]:
        size = self.redis_client.hget(self.sizes_key, cache_key)
        return int(size) if size else None

    def _remove_tracking(self, cache_key: str) -> int:
        """Remove tracking data. Atomic and idempotent. Returns size removed."""
        result = self._remove_tracking_script(
            keys=[self.sizes_key, self.total_key],
            args=[cache_key],
        )
        return int(result) if result else 0
