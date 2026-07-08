"""
Expiry management for the array/config.json HyperCache.

The HyperCache is built and owned by RemoteConfig (`posthog/models/remote_config.py`);
this module wraps that instance with the shared expiry-tracking machinery
(`cache_expiry_manager` / `hypercache_manager`) so the hourly refresh task keeps the
dedicated flags Redis warm and reads don't fall through to S3.

The refresh path is deliberately lightweight: it re-stamps the last-synced
`RemoteConfig.config` rather than calling `build_config()`, because the daily
`sync_all_remote_configs` already rebuilds content fleet-wide. The hourly task's only
job is to prevent TTL expiry, so re-stamping the persisted blob is enough.
"""

from typing import Any

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.metrics import TOMBSTONE_COUNTER
from posthog.models.remote_config import RemoteConfig
from posthog.models.team.team import Team
from posthog.storage.cache_expiry_manager import (
    cleanup_stale_expiry_tracking as cleanup_generic,
    get_teams_with_expiring_caches as get_teams_generic,
)
from posthog.storage.hypercache_manager import (
    HyperCacheManagementConfig,
    get_cache_stats as get_cache_stats_generic,
    push_hypercache_teams_processed_metrics,
)

logger = structlog.get_logger(__name__)


# Module-level singleton so the management config and refresh task share one instance
# (and tests can patch it); RemoteConfig.get_hypercache() otherwise builds one per call.
remote_config_hypercache = RemoteConfig.get_hypercache()


def update_remote_config_cache(team: Team | int, ttl: int | None = None) -> bool:
    """
    Re-stamp a team's array/config.json Redis entry to prevent TTL expiry.

    Reads the persisted RemoteConfig.config (not build_config()) and writes it
    redis-only with expiry tracking, skipping S3. Returns False without writing when
    the team has no RemoteConfig row or an empty config.

    Args:
        team: Team (or team id) whose cache entry should be refreshed
        ttl: Optional custom TTL in seconds (defaults to the HyperCache's cache_ttl)

    Returns:
        True if the cache entry was re-stamped, False if skipped
    """
    try:
        remote_config = RemoteConfig.objects.select_related("team").get(team=team)
    except RemoteConfig.DoesNotExist:
        logger.debug("No RemoteConfig to refresh", team=team)
        return False

    config = remote_config.config
    if not config:
        return False

    # Pass the loaded Team (the input may be a bare id) so track_expiry fires.
    remote_config_hypercache.set_cache_value_redis_only(remote_config.team, config, ttl=ttl, track_expiry=True)
    return True


REMOTE_CONFIG_HYPERCACHE_MANAGEMENT_CONFIG = HyperCacheManagementConfig(
    hypercache=remote_config_hypercache,
    update_fn=update_remote_config_cache,
    cache_name="remote_config",
)


def refresh_expiring_caches(ttl_threshold_hours: int = 24, limit: int = 5000) -> tuple[int, int]:
    """
    Refresh array/config.json caches expiring within ``ttl_threshold_hours``; returns (successful, failed).

    Batch-loads every expiring team's config in one query — the config lives in a separate
    table from Team, so re-stamping per team would be an N+1.
    """
    teams = get_teams_generic(REMOTE_CONFIG_HYPERCACHE_MANAGEMENT_CONFIG, ttl_threshold_hours, limit)
    if not teams:
        return 0, 0

    team_by_id = {team.id: team for team in teams}
    configs = dict(RemoteConfig.objects.filter(team__in=teams).values_list("team_id", "config"))

    successful = 0
    failed = 0
    for team_id, team in team_by_id.items():
        config = configs.get(team_id)
        if not config:
            # No config (missing row or empty) — nothing to re-stamp.
            failed += 1
            continue
        try:
            remote_config_hypercache.set_cache_value_redis_only(team, config, track_expiry=True)
            successful += 1
        except Exception as e:
            logger.exception("Failed to refresh remote config cache", team_id=team_id)
            capture_exception(e)
            failed += 1

    push_hypercache_teams_processed_metrics(
        namespace=REMOTE_CONFIG_HYPERCACHE_MANAGEMENT_CONFIG.namespace,
        cache_name=REMOTE_CONFIG_HYPERCACHE_MANAGEMENT_CONFIG.cache_name,
        successful=successful,
        failed=failed,
    )
    return successful, failed


def cleanup_stale_expiry_tracking() -> int:
    """
    Remove expiry-tracking entries for teams that no longer exist in the database.

    Returns the number of stale entries removed. Should run daily to keep the
    ``remote_config_cache_expiry`` sorted set from accumulating deleted teams.
    """
    removed = cleanup_generic(REMOTE_CONFIG_HYPERCACHE_MANAGEMENT_CONFIG)

    if removed > 0:
        TOMBSTONE_COUNTER.labels(
            namespace="array",
            operation="stale_expiry_tracking",
            component="remote_config_cache",
        ).inc(removed)

    return removed


def get_cache_stats() -> dict[str, Any]:
    """Coverage / TTL-distribution / size statistics for the array/config.json cache."""
    return get_cache_stats_generic(REMOTE_CONFIG_HYPERCACHE_MANAGEMENT_CONFIG)
