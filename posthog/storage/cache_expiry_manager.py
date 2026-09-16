"""
Generic cache expiry management for Redis-backed caches.

This module provides shared functions for managing cache expiration tracking
across different HyperCache types (flags, team metadata, etc.).
"""

from __future__ import annotations

import time
from typing import Literal

import structlog

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.redis import get_client
from posthog.storage.hypercache_manager import HyperCacheManagementConfig, push_hypercache_teams_processed_metrics

logger = structlog.get_logger(__name__)

RefreshOutcome = Literal["successful", "failed", "enqueued"]


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
        query = config.narrow_team_queryset(Team.objects.filter(**filter_kwargs))

        teams = list(query)

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


def count_expiring_caches(config: HyperCacheManagementConfig, ttl_threshold_hours: int = 24) -> int | None:
    """
    Count the entries due for refresh in the expiry tracking sorted set.

    Deliberately unbounded, unlike get_teams_with_expiring_caches, which stops at the
    run's limit. The count is the sweep's saturation signal: it has to be able to
    exceed what one run processes, or it cannot tell a drained queue from a queue the
    sweep is falling behind on.

    Args:
        config: HyperCache management config specifying which cache to count
        ttl_threshold_hours: Count entries expiring within this many hours

    Returns:
        Number of entries due for refresh, or None if the count is unavailable
    """
    hypercache = config.hypercache

    if not hypercache.expiry_sorted_set_key:
        return None

    try:
        redis_client = get_client(hypercache.redis_url)
        threshold_timestamp = time.time() + (ttl_threshold_hours * 3600)
        return redis_client.zcount(hypercache.expiry_sorted_set_key, "-inf", threshold_timestamp)
    except Exception as e:
        logger.warning(f"Error counting expiring {config.log_prefix}", error=str(e))
        return None


@frozen
class CacheRefreshCounts:
    successful: int
    failed: int
    enqueued: int = 0


@frozen
class RefreshPacing:
    """
    How fast a run may hand teams to `config.route_refresh_fn`.

    Only routed teams are paced. A team the sweep builds itself already takes tens of
    milliseconds, while routing is a message produce, so an unpaced run delivers its
    whole batch in one burst. The receiving builder drains sequentially, so that burst
    sits in front of every message raised after it and delays the work those messages
    stand for.

    Passed per run rather than held on the config, so the values can come from settings
    at call time. The config is built at module import, which would freeze them.
    """

    chunk_size: int
    delay_seconds: float
    window_seconds: float


def refresh_expiring_caches(
    config: HyperCacheManagementConfig,
    ttl_threshold_hours: int = 24,
    limit: int = 5000,
    pacing: RefreshPacing | None = None,
) -> CacheRefreshCounts:
    """
    Refresh caches that are expiring soon to prevent cache misses.

    This is the main hourly job that keeps caches fresh. It:
    1. Finds teams whose caches are expiring within the threshold (up to limit)
    2. Refreshes each cache, either by calling the configured update function or, when
       the config binds a routing hook that claims the team, by handing the refresh to
       the builder behind that hook
    3. Returns successful/failed/enqueued counts, which sum to the number of teams the
       run processed

    A routed team is counted as enqueued and never as successful. Its build happens
    elsewhere and after this run ends, so counting it as successful would report a
    healthy sweep while the other builder was down.

    Args:
        config: HyperCache management config specifying which cache to refresh
        ttl_threshold_hours: Refresh caches expiring within this many hours
        limit: Maximum number of teams to refresh per run (default 5000)
        pacing: Optional pacing for routed teams. Ignored when no team is routed.

    Returns:
        CacheRefreshCounts with successful, failed and enqueued counts
    """
    teams = get_teams_with_expiring_caches(config, ttl_threshold_hours, limit)
    counts = _refresh_teams(config, teams, pacing)

    logger.info(
        f"Completed refreshing {config.log_prefix}",
        successful=counts.successful,
        failed=counts.failed,
        enqueued=counts.enqueued,
        total=len(teams),
    )

    # Push metrics to Pushgateway (Gauges work better than Counters for batch jobs).
    # Pushed on an empty run too, because a backlog that has drained to zero is the
    # reading the gauge exists to make legible, and stale counts from the last
    # non-empty run would hide it.
    push_hypercache_teams_processed_metrics(
        namespace=config.namespace,
        cache_name=config.cache_name,
        successful=counts.successful,
        failed=counts.failed,
        enqueued=counts.enqueued,
        expiry_backlog=count_expiring_caches(config, ttl_threshold_hours),
    )

    return counts


def _refresh_teams(
    config: HyperCacheManagementConfig, teams: list[Team], pacing: RefreshPacing | None
) -> CacheRefreshCounts:
    successful = 0
    failed = 0
    enqueued = 0
    routed_since_pause = 0
    slept_seconds = 0.0
    window_exhausted = False
    last_index = len(teams) - 1

    for index, team in enumerate(teams):
        outcome = _refresh_one_team(config, team)
        if outcome == "enqueued":
            enqueued += 1
        elif outcome == "successful":
            successful += 1
        else:
            failed += 1

        if outcome != "enqueued" or pacing is None or index == last_index:
            continue

        routed_since_pause += 1
        if routed_since_pause < pacing.chunk_size:
            continue

        routed_since_pause = 0
        remaining_window = pacing.window_seconds - slept_seconds
        if remaining_window <= 0:
            # Routing the rest unpaced is worse for the receiving builder than pacing,
            # and better than a run that overlaps the next one.
            if not window_exhausted:
                window_exhausted = True
                logger.warning(
                    f"Pacing window spent while refreshing {config.log_prefix}, routing the rest unpaced",
                    window_seconds=pacing.window_seconds,
                    teams_routed=enqueued,
                )
            continue

        delay = min(pacing.delay_seconds, remaining_window)
        time.sleep(delay)
        slept_seconds += delay

    return CacheRefreshCounts(successful=successful, failed=failed, enqueued=enqueued)


def _refresh_one_team(config: HyperCacheManagementConfig, team: Team) -> RefreshOutcome:
    try:
        if config.route_refresh_fn is not None and config.route_refresh_fn(team):
            return "enqueued"
        return "successful" if config.update_fn(team) else "failed"
    except Exception as e:
        logger.exception(
            f"Failed to refresh {config.log_prefix[:-1]}",
            team_id=team.id,
            error=str(e),
        )
        capture_exception(e)
        return "failed"


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
