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
- Redis TTL: 7 days (configurable via TEAM_METADATA_CACHE_TTL env var)
- Miss TTL: 1 day (configurable via TEAM_METADATA_CACHE_MISS_TTL env var)

Note: Redis adds ~100 bytes overhead per key. S3 storage uses similar compression.
"""

import os
import re
from datetime import UTC, datetime
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


# Cache TTL constants (in seconds) - configurable via environment variables
TEAM_METADATA_CACHE_TTL = int(os.environ.get("TEAM_METADATA_CACHE_TTL", str(60 * 60 * 24 * 7)))  # Default: 7 days
TEAM_METADATA_CACHE_MISS_TTL = int(os.environ.get("TEAM_METADATA_CACHE_MISS_TTL", str(60 * 60 * 24)))  # Default: 1 day

# List of fields to cache - full team object with 38 core fields
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

                if field in ["created_at", "updated_at"]:
                    value = value.isoformat() if value else None
                elif field == "uuid":
                    value = str(value) if value else None
                elif field == "organization_id":
                    value = str(team.organization_id) if team.organization_id else None
                elif field == "session_recording_sample_rate":
                    value = float(value) if value is not None else None

                metadata[field] = value

            metadata["organization_name"] = (
                team.organization.name if hasattr(team, "organization") and team.organization else None
            )
            metadata["project_name"] = team.project.name if hasattr(team, "project") and team.project else None
            metadata["last_updated"] = datetime.now(UTC).isoformat()

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

# Use dedicated flags cache if available, otherwise fall back to shared cache
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


def update_team_metadata_cache(team: Team | str | int) -> bool:
    """
    Update the metadata cache for a specific team.

    Args:
        team: Team object, API token string, or team ID

    Returns:
        True if cache update succeeded, False otherwise
    """
    success = team_metadata_hypercache.update_cache(team)
    team_id = team.id if isinstance(team, Team) else "unknown"

    if not success:
        logger.warning("Failed to update metadata cache", team_id=team_id)

    return success


def clear_team_metadata_cache(team: Team | str | int, kinds: list[str] | None = None) -> None:
    """
    Clear the metadata cache for a team.

    Args:
        team: Team object, API token string, or team ID
        kinds: Optional list of cache types to clear (["redis", "s3"])
    """
    team_metadata_hypercache.clear_cache(team, kinds=kinds)


# ===================================================================
# Batch refresh operations
# ===================================================================


def get_teams_needing_refresh(
    ttl_threshold_hours: int = 24,
    batch_size: int = 100,
) -> list[Team]:
    """
    Get teams that need their cache refreshed.

    Strategy:
    1. Teams with expiring caches (within ttl_threshold_hours), prioritizing oldest first
    2. Active teams with missing caches (fallback if we have capacity)

    Note: Recently updated teams are handled by Django signals, so we don't need to
    explicitly refresh them here.

    Args:
        ttl_threshold_hours: Refresh caches that will expire within this many hours
        batch_size: Maximum number of teams to return

    Returns:
        List of Team objects that need cache refresh, ordered by priority
    """
    teams_to_refresh: list[Team] = []

    expiring_tokens: list[str] = []
    try:
        redis_client = get_client()
        pattern = f"cache/team_tokens/*/team_metadata/full_metadata.json"

        ttl_threshold_seconds = ttl_threshold_hours * 3600
        token_pattern = r"cache/team_tokens/([^/]+)/"

        for key in redis_client.scan_iter(match=pattern, count=1000):
            if len(expiring_tokens) >= batch_size:
                break

            ttl = redis_client.ttl(key)
            if 0 < ttl < ttl_threshold_seconds:
                key_str = key.decode("utf-8") if isinstance(key, bytes) else key
                match = re.search(token_pattern, key_str)
                if match:
                    expiring_tokens.append(match.group(1))

        if expiring_tokens:
            teams = Team.objects.filter(api_token__in=expiring_tokens).order_by("updated_at")[:batch_size]
            teams_to_refresh.extend(teams)

    except Exception as e:
        logger.warning("Error checking cache TTLs", error=str(e))

    if len(teams_to_refresh) < batch_size:
        remaining = batch_size - len(teams_to_refresh)

        existing_team_ids = [t.id for t in teams_to_refresh]
        additional_teams = (
            Team.objects.exclude(id__in=existing_team_ids)
            .filter(ingested_event=True)
            .order_by("-updated_at")[:remaining]
        )

        teams_to_refresh.extend(additional_teams)

    expiring_tokens_set = set(expiring_tokens)
    logger.info(
        "Found teams needing cache refresh",
        team_count=len(teams_to_refresh),
        expiring_cache_count=len([t for t in teams_to_refresh if t.api_token in expiring_tokens_set]),
    )

    return teams_to_refresh


def refresh_stale_caches(
    ttl_threshold_hours: int = 24,
    batch_size: int = 100,
) -> tuple[int, int]:
    """
    Refresh caches for teams that need it based on intelligent criteria.

    Args:
        ttl_threshold_hours: Refresh caches expiring within this many hours
        batch_size: Maximum number of teams to refresh in one run

    Returns:
        Tuple of (successful_refreshes, failed_refreshes)
    """
    teams = get_teams_needing_refresh(
        ttl_threshold_hours=ttl_threshold_hours,
        batch_size=batch_size,
    )

    successful = 0
    failed = 0

    for team in teams:
        try:
            if update_team_metadata_cache(team):
                successful += 1
            else:
                failed += 1
        except Exception as e:
            logger.exception("Error refreshing cache for team", team_id=team.id, error=str(e))
            capture_exception(e)
            failed += 1

    logger.info(
        "Cache refresh completed",
        successful=successful,
        failed=failed,
        total_teams=len(teams),
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
            import statistics

            size_stats = {
                "sample_count": len(sample_sizes),
                "avg_size_bytes": int(statistics.mean(sample_sizes)),
                "median_size_bytes": int(statistics.median(sample_sizes)),
                "min_size_bytes": min(sample_sizes),
                "max_size_bytes": max(sample_sizes),
                "estimated_total_mb": round((statistics.mean(sample_sizes) * total_keys) / (1024 * 1024), 2),
            }

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
