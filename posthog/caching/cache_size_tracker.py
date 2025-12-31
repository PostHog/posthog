import time
from typing import Optional

from django.conf import settings
from django.core.cache import cache

import structlog
from prometheus_client import Counter

from posthog import redis

logger = structlog.get_logger(__name__)

CACHE_EVICTION_COUNTER = Counter(
    "query_cache_size_limit_evictions_total",
    "Cache entries evicted due to per-team size limits",
)

CACHE_EVICTION_BYTES_COUNTER = Counter(
    "query_cache_size_limit_evicted_bytes_total",
    "Bytes evicted due to per-team size limits",
)


def get_team_cache_limit(team_id: int) -> int:
    """Get cache limit for team, checking for per-team override in extra_settings."""
    from posthog.models import Team

    try:
        team = Team.objects.only("extra_settings").get(pk=team_id)
        if team.extra_settings and "cache_size_limit_bytes" in team.extra_settings:
            return team.extra_settings["cache_size_limit_bytes"]
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

    def track_cache_write(self, cache_key: str, size_bytes: int) -> None:
        """Track a cache write with its size"""
        # Check if overwriting existing key
        old_size = self._get_key_size(cache_key)
        if old_size:
            self.redis_client.incrby(self.total_key, -old_size)

        # Add/update entry with timestamp as score (for LRU eviction)
        self.redis_client.zadd(self.entries_key, {cache_key: time.time()})
        self.redis_client.hset(self.sizes_key, cache_key, size_bytes)
        self.redis_client.incrby(self.total_key, size_bytes)

        # Set TTL on tracking keys so they auto-expire for inactive teams
        # Use cache TTL + 1 day buffer to ensure tracking outlives cached data
        tracking_ttl = settings.CACHED_RESULTS_TTL + 86400
        self.redis_client.expire(self.entries_key, tracking_ttl)
        self.redis_client.expire(self.sizes_key, tracking_ttl)
        self.redis_client.expire(self.total_key, tracking_ttl)

    def get_total_size(self) -> int:
        return int(self.redis_client.get(self.total_key) or 0)

    def evict_until_under_limit(self, limit_bytes: int, new_entry_size: int) -> list[str]:
        """
        Evict oldest entries (LRU) until total + new_entry_size <= limit.
        Lazy cleanup happens here - removes tracking for TTL-expired keys.
        """
        evicted_keys = []
        current_size = self.get_total_size()

        while current_size + new_entry_size > limit_bytes:
            # Get oldest entry (lowest score = oldest timestamp)
            oldest = self.redis_client.zrange(self.entries_key, 0, 0)
            if not oldest:
                break

            cache_key = oldest[0].decode()
            size = self._get_key_size(cache_key) or 0

            # Check if key still exists (lazy cleanup for TTL-expired keys)
            if cache.get(cache_key) is None:
                # Already expired via TTL, just clean up tracking
                self._remove_tracking(cache_key, size)
                current_size -= size
                continue

            cache.delete(cache_key)
            self._remove_tracking(cache_key, size)

            current_size -= size
            evicted_keys.append(cache_key)

            # Update metrics
            CACHE_EVICTION_COUNTER.inc()
            CACHE_EVICTION_BYTES_COUNTER.inc(size)

        return evicted_keys

    def _get_key_size(self, cache_key: str) -> Optional[int]:
        size = self.redis_client.hget(self.sizes_key, cache_key)
        return int(size) if size else None

    def _remove_tracking(self, cache_key: str, size: int) -> None:
        """Remove all tracking data for a cache key."""
        self.redis_client.zrem(self.entries_key, cache_key)
        self.redis_client.hdel(self.sizes_key, cache_key)
        self.redis_client.incrby(self.total_key, -size)
