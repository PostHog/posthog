import time
from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.core.cache import cache

import structlog
from prometheus_client import Counter, Histogram

from posthog import redis
from posthog.cache_utils import cache_for

logger = structlog.get_logger(__name__)

CACHE_EVICTION_COUNTER = Counter(
    "query_cache_size_limit_evictions_total",
    "Cache entries evicted due to per-team size limits",
)

CACHE_EVICTION_BYTES_COUNTER = Counter(
    "query_cache_size_limit_evicted_bytes_total",
    "Bytes evicted due to per-team size limits",
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
        1_000_000_000,  # 1GB
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

return redis.call('GET', total_key)
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
    return settings.TEAM_CACHE_SIZE_LIMIT_BYTES


class TeamCacheSizeTracker:
    """
    Tracks cache size per team using Redis data structures.

    Redis keys used:
    - posthog:cache_sizes:{team_id} - Sorted set: member=cache_key, score=timestamp (for LRU ordering)
    - posthog:cache_entry_sizes:{team_id} - Hash: field=cache_key, value=size (for O(1) size lookup)
    - posthog:cache_total:{team_id} - String counter: total bytes (for O(1) total size lookup)
    """

    def __init__(self, team_id: int):
        self.team_id = team_id
        self.entries_key = f"posthog:cache_sizes:{team_id}"
        self.sizes_key = f"posthog:cache_entry_sizes:{team_id}"
        self.total_key = f"posthog:cache_total:{team_id}"
        self.redis_client = redis.get_client()
        self._track_write_script = self.redis_client.register_script(TRACK_CACHE_WRITE_SCRIPT)
        self._remove_tracking_script = self.redis_client.register_script(REMOVE_TRACKING_SCRIPT)

    def set(self, cache_key: str, data: bytes, data_size: int, ttl: int) -> list[str]:
        """
        Set cache data with size limit enforcement.
        Handles eviction, cache write, and tracking atomically.
        Returns list of evicted keys.
        """
        limit = get_team_cache_limit(self.team_id)
        evicted: list[str] = []

        if self.get_total_size() + data_size > limit:
            evicted = self.evict_until_under_limit(limit, data_size)
            if evicted:
                logger.info(
                    "cache_size_limit_eviction",
                    team_id=self.team_id,
                    evicted_count=len(evicted),
                    limit_bytes=limit,
                )

        cache.set(cache_key, data, ttl)
        self.track_cache_write(cache_key, data_size)
        CACHE_SIZE_HISTOGRAM.observe(self.get_total_size())
        return evicted

    def track_cache_write(self, cache_key: str, size_bytes: int) -> None:
        """Track a cache write with its size. Atomic via Lua script."""
        tracking_ttl = settings.CACHED_RESULTS_TTL + 86400
        self._track_write_script(
            keys=[self.entries_key, self.sizes_key, self.total_key],
            args=[cache_key, size_bytes, time.time(), tracking_ttl],
        )

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

            cache_key = result[0][0]
            if isinstance(cache_key, bytes):
                cache_key = cache_key.decode()

            # Check if key still exists in cache (lazy cleanup for TTL-expired keys)
            if cache_key not in cache:
                # Already expired via TTL, just clean up tracking
                removed_size = self._remove_tracking(cache_key)
                current_size -= removed_size
                continue

            cache.delete(cache_key)
            removed_size = self._remove_tracking(cache_key)

            current_size -= removed_size
            evicted_keys.append(cache_key)

            # Update metrics
            CACHE_EVICTION_COUNTER.inc()
            CACHE_EVICTION_BYTES_COUNTER.inc(removed_size)

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
