"""
Generic cache expiry management for Redis-backed caches.

This module provides a shared abstraction for managing cache expiration tracking
across different cache types (flags, team metadata, etc.). Each cache type can
define a CacheExpiryConfig that specifies how to query and refresh that cache.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.redis import get_client
from posthog.storage.hypercache_manager import HYPERCACHE_TEAMS_PROCESSED_COUNTER

logger = structlog.get_logger(__name__)


@dataclass
class CacheExpiryConfig:
    """
    Configuration for managing cache expiration tracking.

    Each cache type (flags, team metadata, etc.) should define one of these
    configs to specify how its cache expiry is tracked and refreshed.

    Most properties are derived from cache_name to reduce boilerplate.
    """

    # Required properties
    cache_name: str  # Canonical cache name (e.g., "flags", "team_metadata")
    query_field: str  # Team model field to query by ("id" or "api_token")
    identifier_type: type  # Type to convert identifiers to (int or str)
    update_fn: Callable[[Team], bool]  # Function to refresh cache for a team
    namespace: str  # Cache namespace for metrics labeling (e.g., "feature_flags", "team_metadata")
    redis_url: str | None = None  # Optional Redis URL for dedicated cache (e.g., FLAGS_REDIS_URL)

    # Derived properties
    @property
    def sorted_set_key(self) -> str:
        """Redis sorted set key for tracking expiry timestamps."""
        return f"{self.cache_name}_cache_expiry"

    @property
    def log_prefix(self) -> str:
        """Prefix for log messages (e.g., "flags caches", "team metadata caches")."""
        return f"{self.cache_name.replace('_', ' ')} caches"


def track_cache_expiry(sorted_set_key: str, team: Team | int, ttl_seconds: int, redis_url: str | None = None) -> None:
    """
    Track cache expiration in Redis sorted set for efficient expiry queries.

    This is a generic version that works with any sorted set key.
    Cache-specific modules (flags_cache.py, team_metadata_cache.py) may have
    their own wrappers that call this function.

    Args:
        sorted_set_key: Redis sorted set key for tracking expiry
        team: Team object or team ID
        ttl_seconds: TTL in seconds from now
        redis_url: Optional Redis URL for dedicated cache (e.g., FLAGS_REDIS_URL)
    """
    try:
        redis_client = get_client(redis_url)
        team_id = team.id if isinstance(team, Team) else team
        expiry_timestamp = int(time.time()) + ttl_seconds

        # Store team ID with expiry timestamp as score for efficient range queries
        redis_client.zadd(sorted_set_key, {str(team_id): expiry_timestamp})
    except Exception as e:
        # Don't fail the cache update if expiry tracking fails
        logger.warning("Failed to track cache expiry", team_id=team_id, error=str(e))
        capture_exception(e)


def get_teams_with_expiring_caches(
    config: CacheExpiryConfig, ttl_threshold_hours: int = 24, limit: int = 5000
) -> list[Team]:
    """
    Get teams whose caches are expiring soon using sorted set for efficient lookup.

    Uses ZRANGEBYSCORE on the expiry tracking sorted set instead of scanning all Redis keys.
    This is O(log N + M) where M is the number of expiring teams, vs O(N) for SCAN.

    Args:
        config: Cache configuration specifying which cache to check
        ttl_threshold_hours: Refresh caches expiring within this many hours
        limit: Maximum number of teams to return (default 5000, prevents unbounded results)

    Returns:
        List of Team objects whose caches need refresh (up to limit)
    """
    try:
        redis_client = get_client(config.redis_url)

        # Query sorted set for teams expiring within threshold
        threshold_timestamp = time.time() + (ttl_threshold_hours * 3600)

        # Get identifiers of teams expiring before threshold (score is expiration timestamp)
        # Use LIMIT to prevent unbounded results that could cause memory spikes
        expiring_identifiers = redis_client.zrangebyscore(
            config.sorted_set_key, "-inf", threshold_timestamp, start=0, num=limit
        )

        # Decode bytes to strings and convert to appropriate type
        expiring_identifiers = [
            config.identifier_type(identifier.decode("utf-8") if isinstance(identifier, bytes) else identifier)
            for identifier in expiring_identifiers
        ]

        if not expiring_identifiers:
            logger.info(f"No {config.log_prefix} expiring soon")
            return []

        # Build query filter dynamically based on config
        filter_kwargs = {f"{config.query_field}__in": expiring_identifiers}
        teams = list(Team.objects.filter(**filter_kwargs).select_related("organization", "project"))

        logger.info(
            f"Found teams with expiring {config.log_prefix}",
            team_count=len(teams),
            ttl_threshold_hours=ttl_threshold_hours,
        )

        return teams

    except Exception as e:
        logger.exception(f"Error finding expiring {config.log_prefix}", error=str(e))
        capture_exception(e)
        return []


def refresh_expiring_caches(
    config: CacheExpiryConfig, ttl_threshold_hours: int = 24, limit: int = 5000
) -> tuple[int, int]:
    """
    Refresh caches that are expiring soon to prevent cache misses.

    This is the main hourly job that keeps caches fresh. It:
    1. Finds teams whose caches are expiring within the threshold (up to limit)
    2. Refreshes each cache by calling the configured update function
    3. Returns success/failure counts

    Processes teams in batches (default 5000). If more teams are expiring than the limit,
    subsequent runs will process the next batch. This prevents memory spikes and timeouts
    from trying to refresh all teams at once.

    Args:
        config: Cache configuration specifying which cache to refresh
        ttl_threshold_hours: Refresh caches expiring within this many hours
        limit: Maximum number of teams to refresh per run (default 5000)

    Returns:
        Tuple of (successful_count, failed_count)
    """
    teams = get_teams_with_expiring_caches(config, ttl_threshold_hours, limit)

    if not teams:
        logger.info(f"No {config.log_prefix} to refresh")
        return 0, 0

    successful = 0
    failed = 0

    for team in teams:
        try:
            success = config.update_fn(team)
            if success:
                successful += 1
            else:
                failed += 1
        except Exception as e:
            logger.exception(
                f"Failed to refresh {config.log_prefix[:-1]}",
                team_id=team.id,
                error=str(e),
            )
            capture_exception(e)
            failed += 1

    logger.info(
        f"Completed refreshing {config.log_prefix}",
        successful=successful,
        failed=failed,
        total=len(teams),
    )

    # Track metrics using consolidated counters
    HYPERCACHE_TEAMS_PROCESSED_COUNTER.labels(namespace=config.namespace, result="success").inc(successful)
    HYPERCACHE_TEAMS_PROCESSED_COUNTER.labels(namespace=config.namespace, result="failure").inc(failed)

    return successful, failed


def cleanup_stale_expiry_tracking(config: CacheExpiryConfig) -> int:
    """
    Remove stale entries from the expiry tracking sorted set.

    Over time, the sorted set can accumulate entries for deleted teams or teams
    that no longer have caches. This cleanup job removes those stale entries.

    Args:
        config: Cache configuration specifying which cache to clean up

    Returns:
        Number of stale entries removed
    """
    try:
        redis_client = get_client(config.redis_url)

        # Get all entries from the sorted set
        all_identifiers = redis_client.zrange(config.sorted_set_key, 0, -1)

        if not all_identifiers:
            logger.info(f"No {config.log_prefix} expiry entries to check")
            return 0

        # Decode to appropriate type
        all_identifiers = [
            config.identifier_type(identifier.decode("utf-8") if isinstance(identifier, bytes) else identifier)
            for identifier in all_identifiers
        ]

        # Query for valid teams
        filter_kwargs = {f"{config.query_field}__in": all_identifiers}
        valid_identifiers = set(Team.objects.filter(**filter_kwargs).values_list(config.query_field, flat=True))

        # Find stale entries (in sorted set but not in database)
        stale_identifiers = [identifier for identifier in all_identifiers if identifier not in valid_identifiers]

        if not stale_identifiers:
            logger.info(f"No stale {config.log_prefix} expiry entries found")
            return 0

        # Convert back to strings for Redis (sorted sets store members as strings/bytes)
        stale_identifiers_str = [str(identifier) for identifier in stale_identifiers]

        # Remove stale entries
        removed = redis_client.zrem(config.sorted_set_key, *stale_identifiers_str)

        logger.info(
            f"Cleaned up stale {config.log_prefix} expiry entries",
            removed=removed,
            total_checked=len(all_identifiers),
        )

        return removed

    except Exception as e:
        logger.exception(f"Error cleaning up {config.log_prefix} expiry tracking", error=str(e))
        capture_exception(e)
        return 0
