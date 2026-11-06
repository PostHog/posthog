"""
Generic cache expiry management for Redis-backed caches.

This module provides shared functions for managing cache expiration tracking
across different HyperCache types (flags, team metadata, etc.).
"""

from __future__ import annotations

import time
import random
from typing import Literal

import structlog

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.redis import get_client
from posthog.storage.hypercache_manager import HyperCacheManagementConfig, push_hypercache_teams_processed_metrics

logger = structlog.get_logger(__name__)

RefreshOutcome = Literal["successful", "failed", "enqueued"]


@frozen
class ExpiringTeamSelection:
    """The teams one run will refresh, and whether Redis had more to give.

    `limit_reached` is read from the sorted-set range and not from `len(teams)`. A range
    that comes back full of identifiers for deleted teams resolves to fewer Team rows
    than it read, and the run is still leaving work behind. It is None when the range
    could not be read, because a run that never saw the queue cannot report on it.

    The range is capped at the limit, so a run that drained the queue exactly reports
    True as well. `ExpiryBacklogSample.due_count` is the unbounded reading that tells
    those two apart; this flag is the cheap signal on top of it, not a substitute.
    """

    teams: list[Team]
    limit_reached: bool | None


def select_expiring_teams(
    config: HyperCacheManagementConfig, ttl_threshold_hours: int = 24, limit: int = 5000
) -> ExpiringTeamSelection:
    """
    Get teams whose caches are expiring soon using sorted set for efficient lookup.

    Uses ZRANGEBYSCORE on the expiry tracking sorted set instead of scanning all Redis keys.
    This is O(log N + M) where M is the number of expiring teams, vs O(N) for SCAN.

    Args:
        config: HyperCache management config specifying which cache to check
        ttl_threshold_hours: Refresh caches expiring within this many hours
        limit: Maximum number of teams to return (default 5000, prevents unbounded results)

    Returns:
        The teams whose caches need refresh (up to limit), and whether the range filled
    """
    hypercache = config.hypercache

    if not hypercache.expiry_sorted_set_key:
        logger.warning(f"No expiry sorted set configured for {config.log_prefix}")
        return ExpiringTeamSelection(teams=[], limit_reached=False)

    try:
        redis_client = get_client(hypercache.redis_url)

        # Query sorted set for teams expiring within threshold
        threshold_timestamp = _expiry_threshold(ttl_threshold_hours)

        # Get identifiers of teams expiring before threshold (score is expiration timestamp)
        expiring_identifiers = redis_client.zrangebyscore(
            hypercache.expiry_sorted_set_key, "-inf", threshold_timestamp, start=0, num=limit
        )

        limit_reached = len(expiring_identifiers) >= limit

        if not expiring_identifiers:
            logger.info(f"No {config.log_prefix} expiring soon")
            return ExpiringTeamSelection(teams=[], limit_reached=False)

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
            limit_reached=limit_reached,
        )

        return ExpiringTeamSelection(teams=teams, limit_reached=limit_reached)

    except Exception as e:
        logger.exception(f"Error finding expiring {config.log_prefix}", error=str(e))
        capture_exception(e)
        return ExpiringTeamSelection(teams=[], limit_reached=None)


def get_teams_with_expiring_caches(
    config: HyperCacheManagementConfig, ttl_threshold_hours: int = 24, limit: int = 5000
) -> list[Team]:
    """Teams whose caches are expiring soon, for callers that do not report on the run."""
    return select_expiring_teams(config, ttl_threshold_hours, limit).teams


@frozen
class ExpiryBacklogSample:
    """One reading of the expiry sorted set, taken at a single moment.

    `due_count` is deliberately unbounded, unlike `select_expiring_teams`, which stops at
    the run's limit. The count is the sweep's saturation signal: it has to be able to
    exceed what one run processes, or it cannot tell a drained queue from a queue the
    sweep is falling behind on.

    `oldest_seconds_to_expiry` answers the question the count has only ever been a proxy
    for: is anything about to expire before the sweep reaches it. Unlike the count it is
    not inflated by refreshes already in flight. It is not immune to members left behind
    for deleted teams, though: such a member is never re-scored, so it holds the set's
    minimum and pins this reading until `cleanup_stale_expiry_tracking` removes it, and
    that cleanup is a daily task where it is scheduled at all.

    Both are None when Redis does not answer, which pushes no series rather than a zero
    that reads as a drained queue.
    """

    due_count: int | None
    oldest_seconds_to_expiry: float | None


def sample_expiry_backlog(config: HyperCacheManagementConfig, ttl_threshold_hours: int = 24) -> ExpiryBacklogSample:
    """
    Read the expiry tracking sorted set: how much is due, and how urgent the worst is.

    Args:
        config: HyperCache management config specifying which cache to read
        ttl_threshold_hours: Count entries expiring within this many hours

    Returns:
        The reading, with None fields when the sorted set cannot be read
    """
    hypercache = config.hypercache

    if not hypercache.expiry_sorted_set_key:
        return ExpiryBacklogSample(due_count=None, oldest_seconds_to_expiry=None)

    try:
        redis_client = get_client(hypercache.redis_url)
        # One clock for both readings, so the count and the age describe the same moment.
        now = time.time()
        due_count = redis_client.zcount(
            hypercache.expiry_sorted_set_key, "-inf", _expiry_threshold(ttl_threshold_hours, now)
        )
    except Exception as e:
        logger.warning(f"Error reading expiry backlog for {config.log_prefix}", error=str(e))
        return ExpiryBacklogSample(due_count=None, oldest_seconds_to_expiry=None)

    # Guarded separately from the count so that a zrange failure does not discard a
    # zcount that already succeeded.
    try:
        oldest = redis_client.zrange(hypercache.expiry_sorted_set_key, 0, 0, withscores=True)
        # The score is the expiration timestamp, so the value goes negative once the
        # oldest entry is past its expiry and the sweep is behind.
        oldest_seconds = oldest[0][1] - now if oldest else None
    except Exception as e:
        logger.warning(f"Error reading oldest expiry entry for {config.log_prefix}", error=str(e))
        oldest_seconds = None

    return ExpiryBacklogSample(due_count=due_count, oldest_seconds_to_expiry=oldest_seconds)


def _expiry_threshold(ttl_threshold_hours: int, now: float | None = None) -> float:
    """The sorted-set score below which an entry is due for refresh. Shared so the
    backlog gauge always describes the same set the sweep pulls its teams from."""
    return (time.time() if now is None else now) + (ttl_threshold_hours * 3600)


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

    `window_seconds` bounds the total pause, and it is a wall-clock bound for a reason:
    the pause is a `time.sleep` inside the Celery task, so it holds the worker process
    and its database connection, and Celery waits for it on shutdown. Keep the window
    under the worker pod's termination grace period, or a deploy landing mid-run holds
    the pod in Terminating and then kills it before the run pushes its metrics. That is
    also why the window is not expressed as a number of pauses: a pause count stops
    bounding wall-clock the moment someone raises `delay_seconds`.
    """

    chunk_size: int
    delay_seconds: float
    window_seconds: float

    def __post_init__(self) -> None:
        # The loop reads `routed_since_pause < chunk_size`, so a chunk below 1 pauses
        # after every team instead of never. Callers clamp their own settings, but the
        # invariant belongs to the type: the next caller writes its own settings.
        if self.chunk_size < 1:
            raise ValueError(f"chunk_size must be at least 1, got {self.chunk_size}")
        if self.delay_seconds < 0 or self.window_seconds < 0:
            raise ValueError("pacing delays must not be negative")


@frozen
class RefreshRun:
    """Everything a run reads before it touches a team.

    Built in one place because the order matters. Once the run starts, a config with a
    routing hook produces messages for another builder, and those teams stay in the
    sorted set until that builder rebuilds them seconds to minutes later. A backlog
    sample taken after that point counts work that is already in flight, so the only
    clean reading of the queue is the one taken before the first team is processed.

    `ttl_threshold_hours` rides along so the after sample counts the same set the before
    sample did. Passed separately to both ends, the two could drift and their difference
    would stop meaning anything.
    """

    backlog_before: ExpiryBacklogSample
    teams: list[Team]
    limit_reached: bool | None
    ttl_threshold_hours: int


def start_refresh_run(
    config: HyperCacheManagementConfig, ttl_threshold_hours: int = 24, limit: int = 5000
) -> RefreshRun:
    """Sample the expiry backlog, then pick the teams this run will refresh."""
    backlog_before = sample_expiry_backlog(config, ttl_threshold_hours)
    selection = select_expiring_teams(config, ttl_threshold_hours, limit)
    return RefreshRun(
        backlog_before=backlog_before,
        teams=selection.teams,
        limit_reached=selection.limit_reached,
        ttl_threshold_hours=ttl_threshold_hours,
    )


def push_refresh_metrics(
    config: HyperCacheManagementConfig,
    run: RefreshRun,
    counts: CacheRefreshCounts,
) -> None:
    """
    Push a refresh run's counts and its expiry backlog to Pushgateway.

    Every sweep over the expiry sorted set ends here, including the batch-loading fork
    in remote_config_cache. One function so the next field added reaches both without
    anyone having to remember the fork exists.

    Both ends of the run are pushed, because neither reading means anything alone. The
    before sample is the clean one, taken before the run touches a team.

    A member leaves the due window only when something writes its cache and re-scores it.
    So `before - after` is what a run that builds its own teams drained. A run that routes
    its refreshes writes nothing, so its teams hold their scores until the other builder
    rebuilds them, and the same subtraction returns close to zero.

    One run's before sample minus the previous run's after sample is the net change
    between runs, not an arrival rate. Rebuilds that complete in the gap re-score out of
    the window and cancel part of the arrivals.

    To see whether the queue is growing, read the before series run over run. Its slope is
    arrivals minus completions, so a rising series means the sweep is falling behind.
    Nothing here counts entries as they enter the window.

    An empty run pushes too. Pushgateway keeps serving the last value pushed, so
    skipping it would latch a drained backlog at whatever the last busy run saw.
    """
    backlog_after = sample_expiry_backlog(config, run.ttl_threshold_hours)

    push_hypercache_teams_processed_metrics(
        namespace=config.namespace,
        cache_name=config.cache_name,
        successful=counts.successful,
        failed=counts.failed,
        enqueued=counts.enqueued,
        expiry_backlog=backlog_after.due_count,
        expiry_backlog_before=run.backlog_before.due_count,
        oldest_expiry_seconds=run.backlog_before.oldest_seconds_to_expiry,
        limit_reached=run.limit_reached,
    )


def refresh_expiring_caches(
    config: HyperCacheManagementConfig,
    ttl_threshold_hours: int = 24,
    limit: int = 5000,
    pacing: RefreshPacing | None = None,
) -> CacheRefreshCounts:
    """
    Refresh caches that are expiring soon to prevent cache misses.

    This is the main hourly job that keeps caches fresh. It:
    1. Samples the expiry backlog, then finds teams whose caches are expiring within the
       threshold (up to limit)
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
    run = start_refresh_run(config, ttl_threshold_hours, limit)
    counts = _refresh_teams(config, run.teams, pacing)

    logger.info(
        f"Completed refreshing {config.log_prefix}",
        successful=counts.successful,
        failed=counts.failed,
        enqueued=counts.enqueued,
        total=len(run.teams),
        limit_reached=run.limit_reached,
        backlog_before=run.backlog_before.due_count,
    )

    push_refresh_metrics(config, run, counts)

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


def _staggered_refresh_ttl(config: HyperCacheManagementConfig) -> int | None:
    """The band only ever shortens: an entry that outlived `cache_ttl` would break
    whatever staleness bound that TTL was chosen to enforce.
    """
    fraction = config.refresh_ttl_min_fraction
    if fraction is None:
        return None
    cache_ttl = config.hypercache.cache_ttl
    # The floor is truncated to an int, so a short enough cache_ttl gives a floor of zero.
    # Redis treats a timeout of zero as expired, so the entry would come due on arrival.
    floor = max(1, int(cache_ttl * fraction))
    return random.randint(floor, cache_ttl)


def _refresh_one_team(config: HyperCacheManagementConfig, team: Team) -> RefreshOutcome:
    try:
        if config.route_refresh_fn is not None and config.route_refresh_fn(team.id):
            return "enqueued"
        return "successful" if config.update_fn(team, ttl=_staggered_refresh_ttl(config)) else "failed"
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
