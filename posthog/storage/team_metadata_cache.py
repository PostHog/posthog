"""
Team metadata HyperCache - Full team object caching using existing HyperCache infrastructure.

This module provides dedicated caching of complete Team objects (39 fields) using the
existing HyperCache system which handles Redis + S3 backup automatically.

Memory Usage Estimation:
------------------------
Cache size varies significantly based on your team configurations. Factors include:
- Number of configured features (recording settings, survey configs, etc.)
- Length of organization and team names
- Number of populated optional fields
- Complexity of JSON configuration objects

Typical ranges (based on preliminary analysis):
- Per team: 10-30 KB compressed in Redis
- Compression ratio: 2-4:1 from raw JSON

To get accurate estimates for your data, run:
    python manage.py analyze_team_cache_sizes

Tool will sample the cache and provide percentile-based memory projections.

Configuration:
-------------------
- Redis TTL: 7 days (configurable via TEAM_METADATA_CACHE_TTL env var)
- Miss TTL: 1 day (configurable via TEAM_METADATA_CACHE_MISS_TTL env var)

Cache Invalidation:
-------------------
Caches are invalidated automatically when:
- Team is saved (via Django signal → Celery task)
- Team is deleted (via Django signal → immediate clear)
- Hourly refresh job detects expiring entries (TTL < 24h)

Manual invalidation:
    from posthog.storage.team_metadata_cache import clear_team_metadata_cache
    clear_team_metadata_cache(team_id)

Note: Redis adds ~100 bytes overhead per key. S3 storage uses similar compression.
"""

import os
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import structlog

from posthog.caching.flags_redis_cache import FLAGS_DEDICATED_CACHE_ALIAS
from posthog.metrics import TOMBSTONE_COUNTER
from posthog.models.team.team import Team
from posthog.redis import get_client
from posthog.storage.cache_expiry_manager import (
    cleanup_stale_expiry_tracking as cleanup_generic,
    get_teams_with_expiring_caches as get_teams_generic,
    refresh_expiring_caches as refresh_generic,
)
from posthog.storage.hypercache import HyperCache, HyperCacheStoreMissing, KeyType
from posthog.storage.hypercache_manager import (
    HyperCacheManagementConfig,
    get_cache_stats as get_cache_stats_generic,
)

logger = structlog.get_logger(__name__)


TEAM_METADATA_CACHE_TTL = int(os.environ.get("TEAM_METADATA_CACHE_TTL", str(60 * 60 * 24 * 7)))
TEAM_METADATA_CACHE_MISS_TTL = int(os.environ.get("TEAM_METADATA_CACHE_MISS_TTL", str(60 * 60 * 24)))

# Sorted set key for tracking cache expirations
TEAM_CACHE_EXPIRY_SORTED_SET = "team_metadata_cache_expiry"

# NOTE: Includes secret tokens (api_token, secret_api_token, secret_api_token_backup)
# for flags service consumption. These are stored in dedicated redis + potentially S3.
# This is acceptable for our threat model where flags service needs auth tokens to validate requests.
TEAM_METADATA_FIELDS = [
    "id",
    "project_id",
    "organization_id",
    "uuid",
    "name",
    "api_token",
    "secret_api_token",
    "secret_api_token_backup",
    "timezone",
    "extra_settings",
    "session_recording_opt_in",
    "session_recording_sample_rate",
    "session_recording_minimum_duration_milliseconds",
    "session_recording_linked_flag",
    "session_recording_network_payload_capture_config",
    "session_recording_masking_config",
    "session_recording_url_trigger_config",
    "session_recording_url_blocklist_config",
    "session_recording_event_trigger_config",
    "session_recording_trigger_match_type_config",
    "session_replay_config",
    "recording_domains",
    "cookieless_server_hash_mode",
    "survey_config",
    "surveys_opt_in",
    "product_tours_opt_in",
    "capture_console_log_opt_in",
    "capture_performance_opt_in",
    "capture_dead_clicks",
    "autocapture_opt_out",
    "autocapture_exceptions_opt_in",
    "autocapture_exceptions_errors_to_ignore",
    "autocapture_web_vitals_opt_in",
    "autocapture_web_vitals_allowed_metrics",
    "logs_settings",
    "conversations_enabled",
    "conversations_settings",
    "inject_web_apps",
    "heatmaps_opt_in",
    "flags_persistence_default",
]


# ===================================================================
# Private helpers
# ===================================================================


def _serialize_team_field(field: str, value: Any) -> Any:
    """
    Convert a team field value to cache-serializable format.

    Args:
        field: Field name from TEAM_METADATA_FIELDS
        value: Raw field value from Team model

    Returns:
        Serialized value suitable for JSON encoding
    """
    if field == "uuid":
        return str(value) if value else None
    elif field == "organization_id":
        return str(value) if value else None
    elif field == "session_recording_sample_rate":
        # Match the logic in decide.py and remote_config.py:
        # - Convert Decimal to string directly (preserves precision like "1.00")
        # - Return None for 100% sampling (no sampling needed)
        if value is not None:
            str_value = str(value)
            if str_value == "1.00":
                return None
            return str_value
        return None
    return value


def _serialize_team_to_metadata(team: Team) -> dict[str, Any]:
    """
    Serialize a Team object to metadata dictionary.

    Args:
        team: Team object with organization and project already loaded

    Returns:
        Dictionary containing full team metadata
    """
    metadata = {}
    for field in TEAM_METADATA_FIELDS:
        value = getattr(team, field, None)
        metadata[field] = _serialize_team_field(field, value)

    metadata["organization_name"] = team.organization.name if team.organization else None
    metadata["project_name"] = team.project.name if team.project else None

    return metadata


def _batch_load_team_metadata(teams: list[Team]) -> dict[int, dict[str, Any]]:
    """
    Load metadata for multiple teams efficiently.

    Used by warm_caches() to avoid N+1 queries when warming the cache.
    Teams are already loaded with select_related("organization", "project")
    by the warming framework, so this just serializes them.

    Args:
        teams: List of Team objects with organization/project pre-loaded

    Returns:
        Dict mapping team_id -> metadata dict
    """
    return {team.id: _serialize_team_to_metadata(team) for team in teams}


def _load_team_metadata(team_key: KeyType) -> dict[str, Any] | HyperCacheStoreMissing:
    """
    Load full team metadata from the database.

    Args:
        team_key: Team identifier (can be Team object, API token string, or team ID)

    Returns:
        Dictionary containing full team metadata, or HyperCacheStoreMissing if team not found
    """
    try:
        with transaction.atomic():
            team = HyperCache.team_from_key(team_key)

            if isinstance(team, Team) and (not Team.organization.is_cached(team) or not Team.project.is_cached(team)):
                team = Team.objects.select_related("organization", "project").get(id=team.id)

            return _serialize_team_to_metadata(team)

    except Team.DoesNotExist:
        logger.debug("Team not found for cache lookup")
        return HyperCacheStoreMissing()

    except Exception as e:
        logger.exception(
            "Error loading team metadata",
            error_type=type(e).__name__,
            team_key_type=type(team_key).__name__,
        )
        return HyperCacheStoreMissing()


# ===================================================================
# Module initialization
# ===================================================================

team_metadata_hypercache = HyperCache(
    namespace="team_metadata",
    value="full_metadata.json",
    token_based=True,
    load_fn=_load_team_metadata,
    batch_load_fn=_batch_load_team_metadata,
    cache_ttl=TEAM_METADATA_CACHE_TTL,
    cache_miss_ttl=TEAM_METADATA_CACHE_MISS_TTL,
    cache_alias=FLAGS_DEDICATED_CACHE_ALIAS if FLAGS_DEDICATED_CACHE_ALIAS in settings.CACHES else None,
    expiry_sorted_set_key=TEAM_CACHE_EXPIRY_SORTED_SET,
)


# ===================================================================
# Public API - Core cache operations
# ===================================================================


def get_team_metadata(team: Team | str | int) -> dict[str, Any] | None:
    """
    Get full team metadata from cache.

    Args:
        team: Team object, API token string, or team ID

    Returns:
        Dictionary with team metadata or None if not found
    """
    return team_metadata_hypercache.get_from_cache(team)


def verify_team_metadata(
    team: Team,
    db_batch_data: dict | None = None,
    cache_batch_data: dict | None = None,
    verbose: bool = False,
) -> dict:
    """
    Verify a team's metadata cache against the database.

    Args:
        team: Team to verify (must be a Team object with organization/project loaded)
        db_batch_data: Pre-loaded DB data from batch_load_fn (keyed by team.id)
        cache_batch_data: Pre-loaded cache data from batch_get_from_cache (keyed by team.id)
        verbose: If True, include detailed diffs with field-level differences

    Returns:
        Dict with 'status' ("match", "miss", "mismatch") and 'issue' type.
        When verbose=True, includes 'diffs' list with detailed diff information.
    """
    # Get cached data - use pre-loaded batch data if available (single MGET for whole batch)
    if cache_batch_data and team.id in cache_batch_data:
        cached_data, source = cache_batch_data[team.id]
    else:
        # Fall back to individual lookup
        cached_data = get_team_metadata(team)
        source = "redis" if cached_data else "miss"

    # Handle cache miss
    if not cached_data or source == "miss":
        return {
            "status": "miss",
            "issue": "CACHE_MISS",
            "details": "No cached data found",
        }

    # Get database comparison data - use db_batch_data if available to avoid redundant serialization
    if db_batch_data and team.id in db_batch_data:
        db_data = db_batch_data[team.id]
    else:
        db_data = _serialize_team_to_metadata(team)

    # Compare only fields we care about (defined in TEAM_METADATA_FIELDS + derived fields).
    # This allows removing fields from the cache without triggering unnecessary fixes.
    fields_to_check = set(TEAM_METADATA_FIELDS) | {"organization_name", "project_name"}
    diffs = []
    for key in fields_to_check:
        db_val = db_data.get(key)
        cached_val = cached_data.get(key)
        if db_val != cached_val:
            diffs.append({"field": key, "db_value": db_val, "cached_value": cached_val})

    if not diffs:
        return {"status": "match", "issue": "", "details": ""}

    # Always include field names for logging; full values only when verbose
    diff_fields = sorted([d["field"] for d in diffs])

    result: dict = {
        "status": "mismatch",
        "issue": "DATA_MISMATCH",
        "details": f"{len(diffs)} field(s) differ",
        "diff_fields": diff_fields,
    }

    if verbose:
        result["diffs"] = diffs

    return result


def update_team_metadata_cache(team: Team | str | int, ttl: int | None = None) -> bool:
    """
    Update the metadata cache for a specific team.

    Expiry tracking is handled automatically by HyperCache.set_cache_value().

    Args:
        team: Team object, API token string, or team ID
        ttl: Optional custom TTL in seconds (defaults to TEAM_METADATA_CACHE_TTL)

    Returns:
        True if cache update succeeded, False otherwise
    """
    success = team_metadata_hypercache.update_cache(team, ttl=ttl)

    if not success:
        team_id = team.id if isinstance(team, Team) else "unknown"
        logger.warning("Failed to update metadata cache", team_id=team_id)

    return success


def _get_team_ids_with_recently_updated_teams(team_ids: list[int]) -> set[int]:
    """
    Batch check which teams have been updated within the grace period.

    When a team is updated, an async task updates the cache. If verification
    runs before the async task completes, it sees a stale cache and tries to
    "fix" it, causing unnecessary work. This grace period lets recent async
    updates complete before treating cache misses as genuine errors.

    Args:
        team_ids: List of team IDs to check

    Returns:
        Set of team IDs that were recently updated (should skip fix)
    """
    grace_period_minutes = settings.TEAM_METADATA_CACHE_VERIFICATION_GRACE_PERIOD_MINUTES
    if grace_period_minutes <= 0 or not team_ids:
        return set()

    cutoff = timezone.now() - timedelta(minutes=grace_period_minutes)
    return set(Team.objects.filter(id__in=team_ids, updated_at__gte=cutoff).values_list("id", flat=True))


# Initialize hypercache management config after update_team_metadata_cache is defined
TEAM_HYPERCACHE_MANAGEMENT_CONFIG = HyperCacheManagementConfig(
    hypercache=team_metadata_hypercache,
    update_fn=update_team_metadata_cache,
    cache_name="team_metadata",
    get_team_ids_to_skip_fix_fn=_get_team_ids_with_recently_updated_teams,
)


def clear_team_metadata_cache(team: Team | str | int, kinds: list[str] | None = None) -> None:
    """
    Clear the metadata cache for a team.

    Args:
        team: Team object, API token string, or team ID
        kinds: Optional list of cache types to clear (["redis", "s3"])
    """
    team_metadata_hypercache.clear_cache(team, kinds=kinds)

    # Remove from expiry tracking sorted set
    try:
        redis_client = get_client(team_metadata_hypercache.redis_url)

        # Derive identifier using HyperCache's centralized logic
        if isinstance(team, Team):
            identifier = team_metadata_hypercache.get_cache_identifier(team)
        elif isinstance(team, str):
            identifier = team  # Already have the token
        else:
            # If team ID, skip sorted set cleanup (rare case)
            return

        redis_client.zrem(TEAM_CACHE_EXPIRY_SORTED_SET, identifier)
    except Exception as e:
        logger.warning("Failed to remove from expiry tracking", error=str(e), error_type=type(e).__name__)


# ===================================================================
# Batch refresh operations
# ===================================================================


def get_teams_with_expiring_caches(ttl_threshold_hours: int = 24, limit: int = 5000) -> list[Team]:
    """
    Get teams whose caches are expiring soon using sorted set for efficient lookup.

    Uses ZRANGEBYSCORE on the expiry tracking sorted set instead of scanning all Redis keys.
    This is O(log N + M) where M is the number of expiring teams, vs O(N) for SCAN.

    Args:
        ttl_threshold_hours: Refresh caches expiring within this many hours
        limit: Maximum number of teams to return (default 5000)

    Returns:
        List of Team objects whose caches need refresh (up to limit)
    """
    return get_teams_generic(TEAM_HYPERCACHE_MANAGEMENT_CONFIG, ttl_threshold_hours, limit)


def refresh_expiring_caches(ttl_threshold_hours: int = 24, limit: int = 5000) -> tuple[int, int]:
    """
    Refresh caches that are expiring soon to prevent cache misses.

    This is the main hourly job that keeps caches fresh. It:
    1. Finds cache entries with TTL < threshold (up to limit)
    2. Refreshes them with new data and full TTL

    Processes teams in batches (default 5000). If more teams are expiring than the limit,
    subsequent runs will process the next batch.

    Note: Metrics are pushed to Pushgateway by refresh_expiring_caches() via push_hypercache_teams_processed_metrics()

    Args:
        ttl_threshold_hours: Refresh caches expiring within this many hours
        limit: Maximum number of teams to refresh per run (default 5000)

    Returns:
        Tuple of (successful_refreshes, failed_refreshes)
    """
    return refresh_generic(TEAM_HYPERCACHE_MANAGEMENT_CONFIG, ttl_threshold_hours, limit)


def cleanup_stale_expiry_tracking() -> int:
    """
    Clean up orphaned entries in the expiry tracking sorted set.

    Removes entries for teams that no longer exist in the database.
    Should be run periodically (e.g., daily) to prevent sorted set bloat.

    Returns:
        Number of stale entries removed
    """
    removed = cleanup_generic(TEAM_HYPERCACHE_MANAGEMENT_CONFIG)

    if removed > 0:
        TOMBSTONE_COUNTER.labels(
            namespace="team_metadata",
            operation="stale_expiry_tracking",
            component="team_metadata_cache",
        ).inc(removed)

    return removed


# ===================================================================
# Stats and observability
# ===================================================================


def get_cache_stats() -> dict[str, Any]:
    """
    Get statistics about the team metadata cache.

    Returns:
        Dictionary with cache statistics including size information
    """
    return get_cache_stats_generic(TEAM_HYPERCACHE_MANAGEMENT_CONFIG)
