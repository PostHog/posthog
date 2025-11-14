"""
Team metadata HyperCache - Full team object caching using existing HyperCache infrastructure.

This module provides dedicated caching of complete Team objects (38 fields) using the
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

Note: Redis adds ~100 bytes overhead per key. S3 storage uses similar compression.
"""

import os
import time
import random
import statistics
from typing import Any

from django.conf import settings
from django.core.cache import cache, caches
from django.db import transaction

import structlog
from posthoganalytics import capture_exception
from prometheus_client import Counter, Gauge, Histogram

from posthog.caching.flags_redis_cache import FLAGS_DEDICATED_CACHE_ALIAS
from posthog.models.team.team import Team
from posthog.redis import get_client
from posthog.storage.hypercache import HyperCache, HyperCacheStoreMissing, KeyType

logger = structlog.get_logger(__name__)


TEAM_METADATA_BATCH_REFRESH_COUNTER = Counter(
    "posthog_team_metadata_batch_refresh",
    "Number of times the team metadata batch refresh job has been run",
    labelnames=["result"],
)

TEAM_METADATA_BATCH_REFRESH_DURATION_HISTOGRAM = Histogram(
    "posthog_team_metadata_batch_refresh_duration_seconds",
    "Time taken to run the team metadata batch refresh job in seconds",
    buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0, float("inf")),
)

TEAM_METADATA_TEAMS_PROCESSED_COUNTER = Counter(
    "posthog_team_metadata_teams_processed",
    "Number of teams processed by the batch refresh job",
    labelnames=["result"],
)

TEAM_METADATA_CACHE_COVERAGE_GAUGE = Gauge(
    "posthog_team_metadata_cache_coverage_percent",
    "Percentage of teams with cached metadata",
)

TEAM_METADATA_CACHE_SIZE_BYTES_GAUGE = Gauge(
    "posthog_team_metadata_cache_size_bytes",
    "Estimated total cache size in bytes",
)

TEAM_METADATA_CACHE_UPDATE_DURATION_HISTOGRAM = Histogram(
    "posthog_team_metadata_cache_update_duration_seconds",
    "Time to update a single team's cache entry",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, float("inf")),
)

TEAM_METADATA_SIGNAL_UPDATE_COUNTER = Counter(
    "posthog_team_metadata_signal_updates",
    "Cache updates triggered by Django signals",
    labelnames=["result"],
)

TEAM_METADATA_CACHE_INVALIDATION_COUNTER = Counter(
    "posthog_team_metadata_cache_invalidations",
    "Full cache invalidations (schema changes)",
)


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
    "app_urls",
    "slack_incoming_webhook",
    "created_at",
    "updated_at",
    "anonymize_ips",
    "completed_snippet_onboarding",
    "has_completed_onboarding_for",
    "onboarding_tasks",
    "ingested_event",
    "person_processing_opt_out",
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
    "session_recording_retention_period",
    "survey_config",
    "surveys_opt_in",
    "capture_console_log_opt_in",
    "capture_performance_opt_in",
    "capture_dead_clicks",
    "autocapture_opt_out",
    "autocapture_web_vitals_opt_in",
    "autocapture_web_vitals_allowed_metrics",
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
    if field in ["created_at", "updated_at"]:
        return value.isoformat() if value else None
    elif field == "uuid":
        return str(value) if value else None
    elif field == "organization_id":
        return str(value) if value else None
    elif field == "session_recording_sample_rate":
        return float(value) if value is not None else None
    return value


def _track_cache_expiry(team: Team | str | int, ttl_seconds: int) -> None:
    """
    Track cache expiration in Redis sorted set for efficient expiry queries.

    Args:
        team: Team object, API token string, or team ID
        ttl_seconds: TTL in seconds from now
    """
    try:
        redis_client = get_client()

        # Get team token for tracking
        if isinstance(team, Team):
            token = team.api_token
        elif isinstance(team, str):
            token = team
        else:
            # If team ID, need to fetch token - but this is rare, skip tracking
            return

        expiration_timestamp = time.time() + ttl_seconds
        redis_client.zadd(TEAM_CACHE_EXPIRY_SORTED_SET, {token: expiration_timestamp})
    except Exception as e:
        logger.warning("Failed to track cache expiry in sorted set", error=str(e), error_type=type(e).__name__)


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

            metadata = {}
            for field in TEAM_METADATA_FIELDS:
                value = getattr(team, field, None)
                metadata[field] = _serialize_team_field(field, value)

            metadata["organization_name"] = (
                team.organization.name if hasattr(team, "organization") and team.organization else None
            )
            metadata["project_name"] = team.project.name if hasattr(team, "project") and team.project else None

            return metadata

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

if FLAGS_DEDICATED_CACHE_ALIAS in settings.CACHES:
    _team_metadata_cache_client = caches[FLAGS_DEDICATED_CACHE_ALIAS]
else:
    _team_metadata_cache_client = cache

team_metadata_hypercache = HyperCache(
    namespace="team_metadata",
    value="full_metadata.json",
    token_based=True,
    load_fn=_load_team_metadata,
    cache_ttl=TEAM_METADATA_CACHE_TTL,
    cache_miss_ttl=TEAM_METADATA_CACHE_MISS_TTL,
    cache_client=_team_metadata_cache_client,
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


def update_team_metadata_cache(team: Team | str | int, ttl: int | None = None) -> bool:
    """
    Update the metadata cache for a specific team.

    Args:
        team: Team object, API token string, or team ID
        ttl: Optional custom TTL in seconds (defaults to TEAM_METADATA_CACHE_TTL)

    Returns:
        True if cache update succeeded, False otherwise
    """
    start = time.time()
    success = team_metadata_hypercache.update_cache(team, ttl=ttl)
    duration = time.time() - start

    TEAM_METADATA_CACHE_UPDATE_DURATION_HISTOGRAM.observe(duration)

    team_id = team.id if isinstance(team, Team) else "unknown"

    if not success:
        logger.warning("Failed to update metadata cache", team_id=team_id, duration=duration)
    else:
        # Track expiration in sorted set for efficient queries
        ttl_seconds = ttl if ttl is not None else TEAM_METADATA_CACHE_TTL
        _track_cache_expiry(team, ttl_seconds)

    return success


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
        redis_client = get_client()

        if isinstance(team, Team):
            token = team.api_token
        elif isinstance(team, str):
            token = team
        else:
            # If team ID, skip sorted set cleanup (rare case)
            return

        redis_client.zrem(TEAM_CACHE_EXPIRY_SORTED_SET, token)
    except Exception as e:
        logger.warning("Failed to remove from expiry tracking", error=str(e), error_type=type(e).__name__)


def invalidate_all_team_metadata_caches() -> int:
    """
    Invalidate all team metadata caches.

    Used internally by warm_all_team_caches when run with --invalidate-first.

    Returns:
        Number of cache keys deleted
    """
    try:
        redis_client = get_client()
        pattern = "cache/team_tokens/*/team_metadata/*"

        deleted = 0
        for key in redis_client.scan_iter(match=pattern, count=1000):
            redis_client.delete(key)
            deleted += 1

        # Clear the expiry tracking sorted set
        redis_client.delete(TEAM_CACHE_EXPIRY_SORTED_SET)

        TEAM_METADATA_CACHE_INVALIDATION_COUNTER.inc()

        logger.info("Invalidated all team metadata caches", deleted_keys=deleted)
        return deleted
    except Exception as e:
        logger.exception("Failed to invalidate team metadata caches", error=str(e))
        capture_exception(e)
        return 0


# ===================================================================
# Batch refresh operations
# ===================================================================


def get_teams_with_expiring_caches(ttl_threshold_hours: int = 24) -> list[Team]:
    """
    Get teams whose caches are expiring soon using sorted set for efficient lookup.

    Uses ZRANGEBYSCORE on the expiry tracking sorted set instead of scanning all Redis keys.
    This is O(log N + M) where M is the number of expiring teams, vs O(N) for SCAN.

    Args:
        ttl_threshold_hours: Refresh caches expiring within this many hours

    Returns:
        List of Team objects whose caches need refresh
    """
    try:
        redis_client = get_client()

        # Query sorted set for teams expiring within threshold
        threshold_timestamp = time.time() + (ttl_threshold_hours * 3600)

        # Get tokens of teams expiring before threshold (score is expiration timestamp)
        expiring_tokens = redis_client.zrangebyscore(TEAM_CACHE_EXPIRY_SORTED_SET, "-inf", threshold_timestamp)

        # Decode bytes to strings
        expiring_tokens = [token.decode("utf-8") if isinstance(token, bytes) else token for token in expiring_tokens]

        if not expiring_tokens:
            logger.info("No caches expiring soon")
            return []

        teams = list(Team.objects.filter(api_token__in=expiring_tokens).select_related("organization", "project"))

        logger.info(
            "Found teams with expiring caches",
            team_count=len(teams),
            ttl_threshold_hours=ttl_threshold_hours,
        )

        return teams

    except Exception as e:
        logger.exception("Error finding expiring caches", error=str(e))
        capture_exception(e)
        return []


def refresh_expiring_caches(ttl_threshold_hours: int = 24) -> tuple[int, int]:
    """
    Refresh caches that are expiring soon to prevent cache misses.

    This is the main hourly job that keeps caches fresh. It:
    1. Finds all cache entries with TTL < threshold (using sorted set)
    2. Refreshes them with new data and full TTL

    Args:
        ttl_threshold_hours: Refresh caches expiring within this many hours

    Returns:
        Tuple of (successful_refreshes, failed_refreshes)
    """
    teams = get_teams_with_expiring_caches(ttl_threshold_hours=ttl_threshold_hours)

    if not teams:
        return 0, 0

    successful = 0
    failed = 0

    for team in teams:
        try:
            if update_team_metadata_cache(team):
                successful += 1
            else:
                failed += 1
        except Exception as e:
            logger.exception("Error refreshing expiring cache", team_id=team.id, error=str(e))
            capture_exception(e)
            failed += 1

    logger.info(
        "Expiring cache refresh completed",
        successful=successful,
        failed=failed,
        total_teams=len(teams),
    )

    return successful, failed


def cleanup_stale_expiry_tracking() -> int:
    """
    Clean up orphaned entries in the expiry tracking sorted set.

    Removes entries for teams that no longer exist in the database.
    Should be run periodically (e.g., daily) to prevent sorted set bloat.

    Returns:
        Number of stale entries removed
    """
    try:
        redis_client = get_client()

        # Get all tokens from sorted set
        all_tokens = redis_client.zrange(TEAM_CACHE_EXPIRY_SORTED_SET, 0, -1)
        all_tokens = [token.decode("utf-8") if isinstance(token, bytes) else token for token in all_tokens]

        if not all_tokens:
            logger.info("No entries in expiry tracking sorted set")
            return 0

        # Query DB for valid tokens
        valid_tokens = set(Team.objects.filter(api_token__in=all_tokens).values_list("api_token", flat=True))

        # Find stale tokens
        stale_tokens = [token for token in all_tokens if token not in valid_tokens]

        # Remove stale entries
        if stale_tokens:
            redis_client.zrem(TEAM_CACHE_EXPIRY_SORTED_SET, *stale_tokens)
            logger.info("Cleaned up stale expiry tracking entries", removed_count=len(stale_tokens))
            return len(stale_tokens)

        logger.info("No stale entries found in expiry tracking")
        return 0

    except Exception as e:
        logger.exception("Error cleaning up stale expiry tracking", error=str(e))
        capture_exception(e)
        return 0


def warm_all_team_caches(
    batch_size: int = 100,
    invalidate_first: bool = False,
    stagger_ttl: bool = True,
    min_ttl_days: int = 5,
    max_ttl_days: int = 7,
) -> tuple[int, int]:
    """
    Warm cache for all teams.

    Run as a management command for initial cache build or when schema changes require
    cache invalidation. Processes all teams in batches with staggered TTLs to avoid
    synchronized expiration. Continues on errors.

    Args:
        batch_size: Number of teams to process at a time
        invalidate_first: If True, clear all caches before warming
        stagger_ttl: If True, randomize TTLs between min/max to avoid synchronized expiration
        min_ttl_days: Minimum TTL in days (when staggering)
        max_ttl_days: Maximum TTL in days (when staggering)

    Returns:
        Tuple of (successful_updates, failed_updates)
    """
    if invalidate_first:
        logger.info("Invalidating all existing caches before warming")
        invalidated = invalidate_all_team_metadata_caches()
        logger.info("Invalidated caches", count=invalidated)

    teams_queryset = Team.objects.select_related("organization", "project")
    total_teams = teams_queryset.count()

    logger.info(
        "Starting cache warm",
        total_teams=total_teams,
        batch_size=batch_size,
        stagger_ttl=stagger_ttl,
        invalidate_first=invalidate_first,
    )

    successful = 0
    failed = 0
    processed = 0

    last_id = 0
    while True:
        batch = list(teams_queryset.filter(id__gt=last_id).order_by("id")[:batch_size])
        if not batch:
            break

        for team in batch:
            try:
                if stagger_ttl:
                    ttl_seconds = random.randint(min_ttl_days * 24 * 3600, max_ttl_days * 24 * 3600)
                    update_team_metadata_cache(team, ttl=ttl_seconds)
                else:
                    update_team_metadata_cache(team)

                successful += 1
            except Exception as e:
                logger.warning(
                    "Failed to warm cache for team",
                    team_id=team.id,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                capture_exception(e)
                failed += 1

            processed += 1

        last_id = batch[-1].id

        if processed % (batch_size * 10) == 0:
            logger.info(
                "Cache warm progress",
                processed=processed,
                total=total_teams,
                successful=successful,
                failed=failed,
                percent=round(100 * processed / total_teams, 1),
            )

    logger.info(
        "Cache warm completed",
        total_teams=total_teams,
        successful=successful,
        failed=failed,
    )

    return successful, failed


# ===================================================================
# Stats and observability
# ===================================================================


def get_cache_stats() -> dict[str, Any]:
    """
    Get statistics about the team metadata cache.

    Returns:
        Dictionary with cache statistics including size information
    """
    try:
        redis_client = get_client()
        # HyperCache uses format: cache/team_tokens/{token}/team_metadata/full_metadata.json
        pattern = f"cache/team_tokens/*/team_metadata/full_metadata.json"

        total_keys = 0
        ttl_buckets = {
            "expired": 0,
            "expires_1h": 0,
            "expires_24h": 0,
            "expires_7d": 0,
            "expires_later": 0,
        }

        sample_sizes: list[int] = []
        sample_limit = 100

        for key in redis_client.scan_iter(match=pattern, count=1000):
            total_keys += 1
            ttl = redis_client.ttl(key)

            if ttl <= 0:
                ttl_buckets["expired"] += 1
            elif ttl <= 3600:
                ttl_buckets["expires_1h"] += 1
            elif ttl <= 86400:
                ttl_buckets["expires_24h"] += 1
            elif ttl <= 604800:
                ttl_buckets["expires_7d"] += 1
            else:
                ttl_buckets["expires_later"] += 1

            if len(sample_sizes) < sample_limit:
                try:
                    memory_usage = redis_client.memory_usage(key)
                    if memory_usage:
                        sample_sizes.append(memory_usage)
                except:
                    pass

        total_teams = Team.objects.count()
        coverage_percent = (total_keys / total_teams * 100) if total_teams else 0

        size_stats = {}
        if sample_sizes:
            avg_size = statistics.mean(sample_sizes)
            estimated_total_bytes = avg_size * total_keys

            size_stats = {
                "sample_count": len(sample_sizes),
                "avg_size_bytes": int(avg_size),
                "median_size_bytes": int(statistics.median(sample_sizes)),
                "min_size_bytes": min(sample_sizes),
                "max_size_bytes": max(sample_sizes),
                "estimated_total_mb": round(estimated_total_bytes / (1024 * 1024), 2),
            }

            TEAM_METADATA_CACHE_SIZE_BYTES_GAUGE.set(estimated_total_bytes)

        return {
            "total_cached": total_keys,
            "total_teams": total_teams,
            "cache_coverage": f"{coverage_percent:.1f}%",
            "cache_coverage_percent": coverage_percent,
            "ttl_distribution": ttl_buckets,
            "size_statistics": size_stats,
            "namespace": team_metadata_hypercache.namespace,
            "note": "Run 'python manage.py analyze_team_cache_sizes' for detailed analysis",
        }

    except Exception as e:
        logger.exception("Error getting cache stats", error=str(e))
        return {
            "error": str(e),
            "namespace": team_metadata_hypercache.namespace,
        }
