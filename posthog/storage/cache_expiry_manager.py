"""
Generic cache expiry management for Redis-backed caches.

This module provides shared functions for managing cache expiration tracking
across different HyperCache types (flags, team metadata, etc.).
"""

from __future__ import annotations

import time

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.redis import get_client
from posthog.storage.hypercache_manager import HyperCacheManagementConfig, push_hypercache_teams_processed_metrics

logger = structlog.get_logger(__name__)


def get_teams_with_expiring_caches(
    config: HyperCacheManagementConfig, ttl_threshold_hours: int = 24, limit: int = 5000
) -> list[Team]:
    """
    Get teams whose caches are expiring soon using sorted set for efficient lookup.

    Uses ZRANGEBYSCORE on the expiry tracking sorted set instead of scanning all Redis keys.
    This is O(log N + M) where M is the number of expiring teams, vs O(N) for SCAN.

    Args:
        config: HyperCache management config specifying which cache to check
        ttl_threshold_hours: Refresh caches expiring within this many hours
        limit: Maximum number of teams to return (default 5000, prevents unbounded results)

    Returns:
        List of Team objects whose caches need refresh (up to limit)
    """
    hypercache = config.hypercache

    if not hypercache.expiry_sorted_set_key:
        logger.warning(f"No expiry sorted set configured for {config.log_prefix}")
        return []

    try:
        redis_client = get_client(hypercache.redis_url)

        # Query sorted set for teams expiring within threshold
        threshold_timestamp = time.time() + (ttl_threshold_hours * 3600)

        # Get identifiers of teams expiring before threshold (score is expiration timestamp)
        expiring_identifiers = redis_client.zrangebyscore(
            hypercache.expiry_sorted_set_key, "-inf", threshold_timestamp, start=0, num=limit
        )

        if not expiring_identifiers:
            logger.info(f"No {config.log_prefix} expiring soon")
            return []

        # Decode bytes to strings and convert to appropriate type based on token_based
        query_field = "api_token" if hypercache.token_based else "id"
        identifier_type = str if hypercache.token_based else int
        decoded_identifiers = [
            identifier_type(identifier.decode("utf-8") if isinstance(identifier, bytes) else identifier)
            for identifier in expiring_identifiers
        ]

        # Build query filter dynamically based on token_based setting
        filter_kwargs = {f"{query_field}__in": decoded_identifiers}
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
    config: HyperCacheManagementConfig, ttl_threshold_hours: int = 24, limit: int = 5000
) -> tuple[int, int]:
    """
    Refresh caches that are expiring soon to prevent cache misses.

    This is the main hourly job that keeps caches fresh. It:
    1. Finds teams whose caches are expiring within the threshold (up to limit)
    2. Refreshes each cache by calling the configured update function
    3. Returns success/failure counts

    Args:
        config: HyperCache management config specifying which cache to refresh
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

    # Push metrics to Pushgateway (Gauges work better than Counters for batch jobs)
    push_hypercache_teams_processed_metrics(
        namespace=config.namespace,
        successful=successful,
        failed=failed,
    )

    return successful, failed


def cleanup_stale_expiry_tracking(config: HyperCacheManagementConfig) -> int:
    """
    Remove stale entries from the expiry tracking sorted set.

    Over time, the sorted set can accumulate entries for deleted teams or teams
    that no longer have caches. This cleanup job removes those stale entries.

    Args:
        config: HyperCache management config specifying which cache to clean up

    Returns:
        Number of stale entries removed
    """
    hypercache = config.hypercache

    if not hypercache.expiry_sorted_set_key:
        logger.warning(f"No expiry sorted set configured for {config.log_prefix}")
        return 0

    try:
        redis_client = get_client(hypercache.redis_url)

        # Get all entries from the sorted set
        all_identifiers = redis_client.zrange(hypercache.expiry_sorted_set_key, 0, -1)

        if not all_identifiers:
            logger.info(f"No {config.log_prefix} expiry entries to check")
            return 0

        # Decode to appropriate type based on token_based setting
        query_field = "api_token" if hypercache.token_based else "id"
        identifier_type = str if hypercache.token_based else int
        decoded_identifiers = [
            identifier_type(identifier.decode("utf-8") if isinstance(identifier, bytes) else identifier)
            for identifier in all_identifiers
        ]

        # Query for valid teams
        filter_kwargs = {f"{query_field}__in": decoded_identifiers}
        valid_identifiers = set(Team.objects.filter(**filter_kwargs).values_list(query_field, flat=True))

        # Find stale entries (in sorted set but not in database)
        stale_identifiers = [identifier for identifier in decoded_identifiers if identifier not in valid_identifiers]

        if not stale_identifiers:
            logger.info(f"No stale {config.log_prefix} expiry entries found")
            return 0

        # Convert back to strings for Redis (sorted sets store members as strings/bytes)
        stale_identifiers_str = [str(identifier) for identifier in stale_identifiers]

        # Remove stale entries
        removed = redis_client.zrem(hypercache.expiry_sorted_set_key, *stale_identifiers_str)

        logger.info(
            f"Cleaned up stale {config.log_prefix} expiry entries",
            removed=removed,
            total_checked=len(decoded_identifiers),
        )

        return removed

    except Exception as e:
        logger.exception(f"Error cleaning up {config.log_prefix} expiry tracking", error=str(e))
        capture_exception(e)
        return 0
