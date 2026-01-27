"""
Flags HyperCache for feature-flags service.

This module provides a HyperCache that stores feature flags for the feature-flags service.
Unlike the local_evaluation.py cache which provides rich data for SDKs (including cohorts
and group type mappings), this cache provides just the raw flag data.

The cache is automatically invalidated when:
- FeatureFlag models are created, updated, or deleted
- Team models are created or deleted (to ensure flag caches are cleaned up)
- FeatureFlagEvaluationTag models are created or deleted
- Tag models are updated (since tag names are cached in evaluation_tags)
- Hourly refresh job detects expiring entries (TTL < 24h)

Cache Key Pattern:
- Uses team_id as the key
- Stored in both Redis and S3 via HyperCache

Configuration:
- Redis TTL: 7 days (configurable via FLAGS_CACHE_TTL env var)
- Miss TTL: 1 day (configurable via FLAGS_CACHE_MISS_TTL env var)

Manual operations:
    from posthog.models.feature_flag.flags_cache import clear_flags_cache
    clear_flags_cache(team_id)
"""

import time
from collections import defaultdict
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.postgres.aggregates import ArrayAgg
from django.db import transaction
from django.db.models import Q
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

import structlog

from posthog.caching.flags_redis_cache import FLAGS_DEDICATED_CACHE_ALIAS
from posthog.metrics import TOMBSTONE_COUNTER
from posthog.models.feature_flag import FeatureFlag
from posthog.models.feature_flag.feature_flag import (
    FeatureFlagEvaluationTag,
    get_feature_flags,
    serialize_feature_flags,
)
from posthog.models.tag import Tag
from posthog.models.team import Team
from posthog.redis import get_client
from posthog.storage.cache_expiry_manager import (
    cleanup_stale_expiry_tracking as cleanup_generic,
    get_teams_with_expiring_caches,
    refresh_expiring_caches,
)
from posthog.storage.hypercache import HyperCache
from posthog.storage.hypercache_manager import (
    HyperCacheManagementConfig,
    get_cache_stats as get_cache_stats_generic,
)

logger = structlog.get_logger(__name__)

# Sorted set key for tracking cache expirations
FLAGS_CACHE_EXPIRY_SORTED_SET = "flags_cache_expiry"


def _get_feature_flags_for_service(team: Team) -> dict[str, Any]:
    """
    Get feature flags for the feature-flags service.

    Fetches all active, non-deleted feature flags for the team and returns them
    wrapped in a dict that HyperCache can serialize. The actual flag data is in the
    "flags" key as a list of flag dictionaries.

    Returns:
        dict: {"flags": [...]} where flags is a list of flag dictionaries
    """
    flags = get_feature_flags(team=team)
    flags_data = serialize_feature_flags(flags)

    logger.info(
        "Loaded feature flags for service cache",
        team_id=team.id,
        project_id=team.project_id,
        flag_count=len(flags_data),
    )

    # Wrap in dict for HyperCache compatibility
    return {"flags": flags_data}


def _get_feature_flags_for_teams_batch(teams: list[Team]) -> dict[int, dict[str, Any]]:
    """
    Batch load feature flags for multiple teams in one query.

    This avoids N+1 queries by loading all flags for all teams at once,
    then grouping them by team_id.

    Args:
        teams: List of Team objects to load flags for

    Returns:
        Dict mapping team_id to {"flags": [...]} for each team
    """
    if not teams:
        return {}

    # Load all flags for all teams in one query with evaluation tags pre-loaded.
    # Note: We intentionally don't select_related("team") here because we only need
    # team_id (already on the model) for grouping, and the Team objects are already
    # loaded by the caller. Avoiding the join saves memory.
    all_flags = list(
        FeatureFlag.objects.filter(team__in=teams, active=True, deleted=False).annotate(
            evaluation_tag_names_agg=ArrayAgg(
                "evaluation_tags__tag__name",
                filter=Q(evaluation_tags__isnull=False),
                distinct=True,
            )
        )
    )

    # Transfer aggregated tag names to model instances
    for flag in all_flags:
        flag._evaluation_tag_names = flag.evaluation_tag_names_agg or []

    # Group flags by team_id
    flags_by_team_id: dict[int, list[FeatureFlag]] = defaultdict(list)
    for flag in all_flags:
        flags_by_team_id[flag.team_id].append(flag)

    # Serialize flags for each team
    result: dict[int, dict[str, Any]] = {}
    for team in teams:
        team_flags = flags_by_team_id.get(team.id, [])
        flags_data = serialize_feature_flags(team_flags)

        logger.info(
            "Loaded feature flags for service cache (batch)",
            team_id=team.id,
            project_id=team.project_id,
            flag_count=len(flags_data),
        )

        result[team.id] = {"flags": flags_data}

    return result


# HyperCache instance for feature-flags service
# Use dedicated flags cache alias if available, otherwise defaults to default cache
flags_hypercache = HyperCache(
    namespace="feature_flags",
    value="flags.json",
    load_fn=lambda key: _get_feature_flags_for_service(HyperCache.team_from_key(key)),
    cache_ttl=settings.FLAGS_CACHE_TTL,
    cache_miss_ttl=settings.FLAGS_CACHE_MISS_TTL,
    cache_alias=FLAGS_DEDICATED_CACHE_ALIAS if FLAGS_DEDICATED_CACHE_ALIAS in settings.CACHES else None,
    batch_load_fn=_get_feature_flags_for_teams_batch,
    expiry_sorted_set_key=FLAGS_CACHE_EXPIRY_SORTED_SET,
)


def get_flags_from_cache(team: Team) -> list[dict[str, Any]] | None:
    """
    Get feature flags from the cache for a team.

    Only operates when FLAGS_REDIS_URL is configured to avoid reading from/writing to shared cache.

    Args:
        team: The team to get flags for

    Returns:
        list: Flag dictionaries (empty list if team has zero flags)
        None: Cache miss or FLAGS_REDIS_URL not configured
    """
    if not settings.FLAGS_REDIS_URL:
        return None

    result = flags_hypercache.get_from_cache(team)
    if result is None:
        return None
    return result.get("flags", [])


def update_flags_cache(team: Team | int, ttl: int | None = None) -> bool:
    """
    Update the flags cache for a team.

    This explicitly updates both Redis and S3 with the latest flag data.
    Only operates when FLAGS_REDIS_URL is configured to avoid writing to shared cache.
    Expiry tracking is handled automatically by HyperCache.set_cache_value().

    Args:
        team: Team object or team ID
        ttl: Optional custom TTL in seconds (defaults to FLAGS_CACHE_TTL)

    Returns:
        True if cache update succeeded, False otherwise
    """
    if not settings.FLAGS_REDIS_URL:
        return False

    success = flags_hypercache.update_cache(team, ttl=ttl)

    if not success:
        team_id = team.id if isinstance(team, Team) else team
        logger.warning("Failed to update flags cache", team_id=team_id)

    return success


def verify_team_flags(
    team: Team,
    db_batch_data: dict | None = None,
    cache_batch_data: dict | None = None,
    verbose: bool = False,
) -> dict:
    """
    Verify a team's flags cache against the database.

    Args:
        team: Team to verify
        db_batch_data: Pre-loaded DB data from batch_load_fn (keyed by team.id)
        cache_batch_data: Pre-loaded cache data from batch_get_from_cache (keyed by team.id)
        verbose: If True, include detailed diffs with flag keys and field-level differences

    Returns:
        Dict with 'status' ("match", "miss", "mismatch") and 'issue' type.
        When verbose=True, includes 'diffs' list with detailed diff information.
    """
    # Get cached data - use pre-loaded batch data if available (single MGET for whole batch)
    if cache_batch_data and team.id in cache_batch_data:
        cached_data, source = cache_batch_data[team.id]
    else:
        # Fall back to individual lookup (shouldn't happen in batch verification)
        cached_data, source = flags_hypercache.get_from_cache_with_source(team)

    # Get flags from database - use db_batch_data if available to avoid N+1 queries
    if db_batch_data and team.id in db_batch_data:
        db_data = db_batch_data[team.id]
    else:
        db_data = _get_feature_flags_for_service(team)
    db_flags = db_data.get("flags", []) if isinstance(db_data, dict) else []

    # Cache miss (source="db" or "miss" means data was not found in cache)
    if source in ("db", "miss"):
        return {
            "status": "miss",
            "issue": "CACHE_MISS",
            "details": f"No cache entry found (team has {len(db_flags)} flags in DB)",
        }

    # Extract cached flags
    cached_flags = cached_data.get("flags", []) if cached_data else []

    # Compare flags by ID
    db_flags_by_id = {flag["id"]: flag for flag in db_flags}
    cached_flags_by_id = {flag["id"]: flag for flag in cached_flags}

    diffs = []

    # Find missing flags (in DB but not in cache)
    for flag_id in db_flags_by_id:
        if flag_id not in cached_flags_by_id:
            diff: dict = {
                "type": "MISSING_IN_CACHE",
                "flag_id": flag_id,
                "flag_key": db_flags_by_id[flag_id].get("key"),
            }
            diffs.append(diff)

    # Find stale flags (in cache but not in DB)
    for flag_id in cached_flags_by_id:
        if flag_id not in db_flags_by_id:
            diff = {
                "type": "STALE_IN_CACHE",
                "flag_id": flag_id,
                "flag_key": cached_flags_by_id[flag_id].get("key"),
            }
            diffs.append(diff)

    # Compare field values for flags that exist in both
    for flag_id in db_flags_by_id:
        if flag_id in cached_flags_by_id:
            db_flag = db_flags_by_id[flag_id]
            cached_flag = cached_flags_by_id[flag_id]
            if db_flag != cached_flag:
                field_diffs = _compare_flag_fields(db_flag, cached_flag)
                diff = {
                    "type": "FIELD_MISMATCH",
                    "flag_id": flag_id,
                    "flag_key": db_flag.get("key"),
                    "diff_fields": [f["field"] for f in field_diffs],
                }
                if verbose:
                    diff["field_diffs"] = field_diffs
                diffs.append(diff)

    if not diffs:
        return {"status": "match", "issue": "", "details": ""}

    # Summarize diffs
    missing_count = sum(1 for d in diffs if d.get("type") == "MISSING_IN_CACHE")
    stale_count = sum(1 for d in diffs if d.get("type") == "STALE_IN_CACHE")
    mismatch_count = sum(1 for d in diffs if d.get("type") == "FIELD_MISMATCH")

    summary_parts = []
    if missing_count > 0:
        summary_parts.append(f"{missing_count} missing")
    if stale_count > 0:
        summary_parts.append(f"{stale_count} stale")
    if mismatch_count > 0:
        summary_parts.append(f"{mismatch_count} mismatched")

    # Build descriptive diff_flags for logging
    diff_flags = []
    for d in sorted(diffs, key=lambda x: x.get("flag_key") or str(x["flag_id"])):
        flag_key = d.get("flag_key") or str(d["flag_id"])
        diff_type = d.get("type")
        if diff_type == "MISSING_IN_CACHE":
            diff_flags.append(f"{flag_key} {{only in db}}")
        elif diff_type == "STALE_IN_CACHE":
            diff_flags.append(f"{flag_key} {{only in cache}}")
        elif diff_type == "FIELD_MISMATCH":
            fields = d.get("diff_fields", [])
            diff_flags.append(f"{flag_key} {{fields: {', '.join(fields)}}}")

    result: dict = {
        "status": "mismatch",
        "issue": "DATA_MISMATCH",
        "details": f"{', '.join(summary_parts)} flags" if summary_parts else "unknown differences",
        "diff_flags": diff_flags,
    }

    if verbose:
        result["diffs"] = diffs

    return result


def _compare_flag_fields(db_flag: dict, cached_flag: dict) -> list[dict]:
    """Compare field values between DB and cached versions of a flag."""
    field_diffs = []
    all_keys = set(db_flag.keys()) | set(cached_flag.keys())

    for key in all_keys:
        db_val = db_flag.get(key)
        cached_val = cached_flag.get(key)

        if db_val != cached_val:
            field_diffs.append({"field": key, "db_value": db_val, "cached_value": cached_val})

    return field_diffs


def _get_team_ids_with_flags() -> set[int]:
    """
    Get the set of team IDs that have at least one active, non-deleted flag.

    Used by verification to skip expensive DB loads for the ~90% of teams
    that have zero flags. For those teams, we just verify the cache contains
    {"flags": []}.
    """
    start_time = time.time()
    result = set(FeatureFlag.objects.filter(active=True, deleted=False).values_list("team_id", flat=True).distinct())
    duration_ms = (time.time() - start_time) * 1000

    logger.info(
        "Loaded team IDs with flags",
        count=len(result),
        duration_ms=round(duration_ms, 2),
    )

    return result


def _get_team_ids_with_recently_updated_flags(team_ids: list[int]) -> set[int]:
    """
    Batch check which teams have active flags updated within the grace period.

    When a flag is updated, an async task updates the cache. If verification
    runs before the async task completes, it sees a stale cache and tries to
    "fix" it, causing unnecessary work. This grace period lets recent async
    updates complete before treating cache misses as genuine errors.

    Only considers active, non-deleted flags. When a flag is deleted or
    deactivated, the cache update removes it, so we shouldn't skip verification
    just because a deleted/inactive flag was recently updated.

    Args:
        team_ids: List of team IDs to check

    Returns:
        Set of team IDs that have recently updated active flags (should skip fix)
    """
    grace_period_minutes = settings.FLAGS_CACHE_VERIFICATION_GRACE_PERIOD_MINUTES
    if grace_period_minutes <= 0 or not team_ids:
        return set()

    cutoff = timezone.now() - timedelta(minutes=grace_period_minutes)
    return set(
        FeatureFlag.objects.filter(team_id__in=team_ids, updated_at__gte=cutoff, active=True, deleted=False)
        .values_list("team_id", flat=True)
        .distinct()
    )


# Initialize hypercache management config after update_flags_cache is defined
FLAGS_HYPERCACHE_MANAGEMENT_CONFIG = HyperCacheManagementConfig(
    hypercache=flags_hypercache,
    update_fn=update_flags_cache,
    cache_name="flags",
    get_team_ids_needing_full_verification_fn=_get_team_ids_with_flags,
    empty_cache_value={"flags": []},
    get_team_ids_to_skip_fix_fn=_get_team_ids_with_recently_updated_flags,
)


def clear_flags_cache(team: Team | int, kinds: list[str] | None = None) -> None:
    """
    Clear the flags cache for a team.

    Only operates when FLAGS_REDIS_URL is configured to avoid writing to shared cache.

    Args:
        team: Team object or team ID
        kinds: Optional list of cache kinds to clear ("redis", "s3")
    """
    if not settings.FLAGS_REDIS_URL:
        return

    flags_hypercache.clear_cache(team, kinds=kinds)

    # Remove from expiry tracking sorted set
    # Note: When team is an int, we use it directly as the identifier. This works
    # because flags_hypercache is ID-based (token_based=False). For token-based
    # caches, callers must pass a Team object to derive the correct identifier.
    try:
        redis_client = get_client(flags_hypercache.redis_url)
        identifier = flags_hypercache.get_cache_identifier(team) if isinstance(team, Team) else team
        redis_client.zrem(FLAGS_CACHE_EXPIRY_SORTED_SET, str(identifier))
    except Exception as e:
        logger.warning("Failed to remove from expiry tracking", error=str(e), error_type=type(e).__name__)


def get_teams_with_expiring_flags_caches(ttl_threshold_hours: int = 24, limit: int = 5000) -> list[Team]:
    """
    Get teams whose flags caches are expiring soon using sorted set for efficient lookup.

    Uses ZRANGEBYSCORE on the expiry tracking sorted set instead of scanning all Redis keys.
    This is O(log N + M) where M is the number of expiring teams, vs O(N) for SCAN.

    Args:
        ttl_threshold_hours: Refresh caches expiring within this many hours
        limit: Maximum number of teams to return (default 5000)

    Returns:
        List of Team objects whose caches need refresh (up to limit)
    """
    return get_teams_with_expiring_caches(FLAGS_HYPERCACHE_MANAGEMENT_CONFIG, ttl_threshold_hours, limit)


def refresh_expiring_flags_caches(ttl_threshold_hours: int = 24, limit: int = 5000) -> tuple[int, int]:
    """
    Refresh flags caches that are expiring soon to prevent cache misses.

    This is the main hourly job that keeps caches fresh. It:
    1. Finds cache entries with TTL < threshold (up to limit)
    2. Refreshes them with new data and full TTL

    Processes teams in batches (default 5000). If more teams are expiring than the limit,
    subsequent runs will process the next batch.

    Note: Metrics are pushed to Pushgateway by refresh_expiring_caches() via push_hypercache_teams_processed_metrics()

    Args:
        ttl_threshold_hours: Refresh caches expiring within this many hours
        limit: Maximum number of teams to refresh per run (default 5000)
               5000 chosen as starting point to balance:
               - Memory efficiency: Doesn't load too many teams into memory at once
               - Throughput: With ~200K teams total, hourly runs can process 120K/day (5000 * 24)
               - Responsiveness: Completes quickly enough to not block other operations

    Returns:
        Tuple of (successful_refreshes, failed_refreshes)
    """
    return refresh_expiring_caches(FLAGS_HYPERCACHE_MANAGEMENT_CONFIG, ttl_threshold_hours, limit)


def cleanup_stale_expiry_tracking() -> int:
    """
    Clean up orphaned entries in the expiry tracking sorted set.

    Removes entries for teams that no longer exist in the database.
    Should be run periodically (e.g., daily) to prevent sorted set bloat.

    Returns:
        Number of stale entries removed
    """
    removed = cleanup_generic(FLAGS_HYPERCACHE_MANAGEMENT_CONFIG)

    if removed > 0:
        TOMBSTONE_COUNTER.labels(
            namespace="flags",
            operation="stale_expiry_tracking",
            component="flags_cache",
        ).inc(removed)

    return removed


def get_cache_stats() -> dict[str, Any]:
    """
    Get statistics about the flags cache.

    Returns:
        Dictionary with cache statistics including size information
    """
    return get_cache_stats_generic(FLAGS_HYPERCACHE_MANAGEMENT_CONFIG)


# Signal handlers for automatic cache invalidation


@receiver(post_save, sender=FeatureFlag)
@receiver(post_delete, sender=FeatureFlag)
def feature_flag_changed_flags_cache(sender, instance: "FeatureFlag", **kwargs):
    """
    Invalidate flags cache when a feature flag is created, updated, or deleted.

    This ensures the feature-flags service always has fresh flag data after any flag changes.
    Only operates when FLAGS_REDIS_URL is configured.
    """
    if not settings.FLAGS_REDIS_URL:
        return

    from posthog.tasks.feature_flags import update_team_service_flags_cache

    # Defer task execution until after the transaction commits to avoid race conditions
    # Note: Metric tracking happens in the task itself to capture actual success/failure result
    transaction.on_commit(lambda: update_team_service_flags_cache.delay(instance.team_id))


@receiver(post_save, sender=Team)
def team_created_flags_cache(sender, instance: "Team", created: bool, **kwargs):
    """
    Warm flags cache when a team is created.

    This ensures the cache is immediately available for new teams.
    Only operates when FLAGS_REDIS_URL is configured.
    """
    if not created or not settings.FLAGS_REDIS_URL:
        return

    from posthog.tasks.feature_flags import update_team_service_flags_cache

    # Defer task execution until after the transaction commits
    # Note: Metric tracking happens in the task itself to capture actual success/failure result
    transaction.on_commit(lambda: update_team_service_flags_cache.delay(instance.id))


@receiver(post_delete, sender=Team)
def team_deleted_flags_cache(sender, instance: "Team", **kwargs):
    """
    Clear flags cache when a team is deleted.

    This ensures we don't have stale cache entries for deleted teams.
    Only operates when FLAGS_REDIS_URL is configured.
    """
    if not settings.FLAGS_REDIS_URL:
        return

    # For unit tests, only clear Redis to avoid S3 timestamp issues with frozen time
    kinds = ["redis"] if settings.TEST else None
    clear_flags_cache(instance, kinds=kinds)


@receiver(post_save, sender=FeatureFlagEvaluationTag)
@receiver(post_delete, sender=FeatureFlagEvaluationTag)
def evaluation_tag_changed_flags_cache(sender, instance: "FeatureFlagEvaluationTag", **kwargs):
    """
    Invalidate flags cache when evaluation tags are added or removed from a flag.

    Evaluation tags are cached as part of the flag data, so changes to the
    FeatureFlagEvaluationTag join table require a cache refresh.
    Only operates when FLAGS_REDIS_URL is configured.
    """
    if not settings.FLAGS_REDIS_URL:
        return

    from posthog.tasks.feature_flags import update_team_service_flags_cache

    team_id = instance.feature_flag.team_id
    transaction.on_commit(lambda: update_team_service_flags_cache.delay(team_id))


@receiver(post_save, sender=Tag)
def tag_changed_flags_cache(sender, instance: "Tag", created: bool, **kwargs):
    """
    Invalidate flags cache when a tag is renamed.

    Tag names are cached in evaluation_tags, so if a tag used by any flag
    is renamed, we need to refresh those teams' caches.
    Only operates when FLAGS_REDIS_URL is configured.
    """
    if created:
        return  # New tags can't be used by any flags yet

    # In practice, update_fields is rarely specified when saving Tags,
    # but this check follows the pattern used elsewhere in the codebase.
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and "name" not in update_fields:
        return

    if not settings.FLAGS_REDIS_URL:
        return

    from posthog.tasks.feature_flags import update_team_service_flags_cache

    for team_id in FeatureFlagEvaluationTag.get_team_ids_using_tag(instance):
        # Capture team_id in closure to avoid late binding issues
        transaction.on_commit(lambda tid=team_id: update_team_service_flags_cache.delay(tid))  # type: ignore[misc]
