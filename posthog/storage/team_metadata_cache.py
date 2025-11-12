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

to will sample the cache and provide percentile-based memory projections.

Configuration:
- Redis TTL: 7 days (configurable via TEAM_METADATA_CACHE_TTL env var)
- Miss TTL: 1 day (configurable via TEAM_METADATA_CACHE_MISS_TTL env var)

Note: Redis adds ~100 bytes overhead per key. S3 storage uses similar compression.
"""

import os
from datetime import UTC, datetime, timedelta
from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction

import structlog

from posthog.models.team.team import Team
from posthog.redis import get_client
from posthog.storage.hypercache import HyperCache, HyperCacheStoreMissing, KeyType

logger = structlog.get_logger(__name__)

# Cache TTL constants (in seconds) - configurable via environment variables
TEAM_METADATA_CACHE_TTL = int(os.environ.get("TEAM_METADATA_CACHE_TTL", str(60 * 60 * 24 * 7)))  # Default: 7 days
TEAM_METADATA_CACHE_MISS_TTL = int(os.environ.get("TEAM_METADATA_CACHE_MISS_TTL", str(60 * 60 * 24)))  # Default: 1 day

# List of fields to cache - full team object with 38 core fields
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
            # Get the team based on the key type using HyperCache helper
            team = HyperCache.team_from_key(team_key)

            # Ensure related objects are loaded - more reliable approach
            if isinstance(team, Team) and not Team.organization.is_cached(team) or not Team.project.is_cached(team):
                team = Team.objects.select_related("organization", "project").get(id=team.id)

            # Build the metadata dictionary with all specified fields
            metadata = {}
            for field in TEAM_METADATA_FIELDS:
                value = getattr(team, field, None)

                # Handle special field types for JSON serialization
                if field in ["created_at", "updated_at"]:
                    value = value.isoformat() if value else None
                elif field == "uuid":
                    value = str(value) if value else None
                elif field == "organization_id":
                    value = str(team.organization_id) if team.organization_id else None
                elif field == "session_recording_sample_rate":
                    # Convert Decimal to float for JSON serialization
                    value = float(value) if value is not None else None

                metadata[field] = value

            # Add computed/related fields - safely access with hasattr checks
            metadata["organization_name"] = (
                team.organization.name if hasattr(team, "organization") and team.organization else None
            )
            metadata["project_name"] = team.project.name if hasattr(team, "project") and team.project else None
            metadata["last_updated"] = datetime.now(UTC).isoformat()

            return metadata

    except Team.DoesNotExist:
        # Log only that a team was not found, without exposing the key
        logger.warning("Team not found for cache lookup")
        return HyperCacheStoreMissing()

    except Exception:
        # Log the error without exposing sensitive team information
        logger.exception("Error loading team metadata")
        return HyperCacheStoreMissing()


# Create the HyperCache instance for team metadata
team_metadata_hypercache = HyperCache(
    namespace="team_metadata",
    value="full_metadata.json",
    token_based=True,  # Use team API token as primary key
    load_fn=_load_team_metadata,
    cache_ttl=TEAM_METADATA_CACHE_TTL,
    cache_miss_ttl=TEAM_METADATA_CACHE_MISS_TTL,
)


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

    if success:
        team_id = team.id if isinstance(team, Team) else "unknown"
        logger.info("Updated metadata cache", team_id=team_id)
    else:
        team_id = team.id if isinstance(team, Team) else "unknown"
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

    team_id = team.id if isinstance(team, Team) else "unknown"
    logger.info("Cleared metadata cache", team_id=team_id)


def get_teams_needing_refresh(
    ttl_threshold_hours: int = 24,
    recently_updated_hours: int = 1,
    batch_size: int = 100,
) -> list[Team]:
    """
    Get teams that need their cache refreshed based on intelligent criteria.

    Strategy:
    1. Teams that have been updated recently (within recently_updated_hours)
    2. Teams whose cache entries are about to expire (within ttl_threshold_hours)
    3. Teams that are frequently accessed but have stale caches

    Args:
        ttl_threshold_hours: Refresh caches that will expire within this many hours
        recently_updated_hours: Include teams updated within this many hours
        batch_size: Maximum number of teams to return

    Returns:
        List of Team objects that need cache refresh
    """
    import re

    from django.utils import timezone

    teams_to_refresh = []
    now = timezone.now()

    # 1. Get teams updated recently (these likely have stale cache)
    recent_cutoff = now - timedelta(hours=recently_updated_hours)
    recently_updated = Team.objects.filter(updated_at__gte=recent_cutoff).values_list("id", flat=True)[
        : batch_size // 2
    ]

    teams_to_refresh.extend(list(recently_updated))

    # 2. Check Redis TTLs to find caches about to expire
    try:
        redis_client = get_client()
        # HyperCache uses format: cache/team_tokens/{token}/team_metadata/full_metadata.json
        pattern = f"cache/team_tokens/*/team_metadata/*"

        # Scan for all team metadata cache keys
        cache_keys = []
        for key in redis_client.scan_iter(match=pattern, count=1000):
            cache_keys.append(key)
            if len(cache_keys) >= batch_size * 2:  # Check more than we need
                break

        # Check TTLs and find ones expiring soon
        ttl_threshold_seconds = ttl_threshold_hours * 3600
        expiring_soon = []

        # Regex to extract token from HyperCache key format
        token_pattern = r"cache/team_tokens/([^/]+)/"

        for key in cache_keys:
            ttl = redis_client.ttl(key)
            if 0 < ttl < ttl_threshold_seconds:
                # Extract token from the key
                key_str = key.decode("utf-8") if isinstance(key, bytes) else key

                match = re.search(token_pattern, key_str)
                if match:
                    token = match.group(1)
                    try:
                        team = Team.objects.get(api_token=token)
                        expiring_soon.append(team.id)
                    except Team.DoesNotExist:
                        pass

        # Add teams with expiring caches
        remaining_slots = batch_size - len(teams_to_refresh)
        teams_to_refresh.extend(expiring_soon[:remaining_slots])

    except Exception as e:
        logger.warning("Error checking cache TTLs", error=str(e))

    # Remove duplicates and fetch the actual Team objects
    unique_team_ids = list(set(teams_to_refresh))[:batch_size]

    if unique_team_ids:
        teams = Team.objects.filter(id__in=unique_team_ids)
        logger.info(
            "Found teams needing cache refresh",
            team_count=len(teams),
            recently_updated_count=len(recently_updated),
            expiring_soon_count=len(expiring_soon),
        )
        return list(teams)

    return []


def refresh_stale_caches(
    ttl_threshold_hours: int = 24,
    recently_updated_hours: int = 1,
    batch_size: int = 100,
) -> tuple[int, int]:
    """
    Refresh caches for teams that need it based on intelligent criteria.

    Args:
        ttl_threshold_hours: Refresh caches expiring within this many hours
        recently_updated_hours: Include teams updated within this many hours
        batch_size: Maximum number of teams to refresh in one run

    Returns:
        Tuple of (successful_refreshes, failed_refreshes)
    """
    teams = get_teams_needing_refresh(
        ttl_threshold_hours=ttl_threshold_hours,
        recently_updated_hours=recently_updated_hours,
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
            failed += 1

    logger.info(
        "Cache refresh completed",
        successful=successful,
        failed=failed,
        total_teams=len(teams),
    )

    return successful, failed


def get_cache_stats() -> dict[str, Any]:
    """
    Get statistics about the team metadata cache.

    Returns:
        Dictionary with cache statistics including size information
    """
    try:
        redis_client = get_client()
        # HyperCache uses format: cache/team_tokens/{token}/team_metadata/full_metadata.json
        pattern = f"cache/team_tokens/*/team_metadata/*"

        total_keys = 0
        ttl_buckets = {
            "expired": 0,
            "expires_1h": 0,
            "expires_24h": 0,
            "expires_7d": 0,
            "expires_later": 0,
        }

        # Sample size statistics
        sample_sizes: list[int] = []
        sample_limit = 100  # Sample first 100 entries for size stats

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

            # Sample memory usage for size statistics
            if len(sample_sizes) < sample_limit:
                try:
                    # Get actual memory usage from Redis (if available)
                    memory_usage = redis_client.memory_usage(key)
                    if memory_usage:
                        sample_sizes.append(memory_usage)
                except:
                    # MEMORY USAGE command might not be available
                    pass

        # Get total teams for comparison
        total_teams = Team.objects.count()

        # Calculate size statistics if we have samples
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
            "cache_coverage": f"{(total_keys / total_teams * 100):.1f}%" if total_teams else "0%",
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
