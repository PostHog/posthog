"""
Team metadata HyperCache - Full team object caching using existing HyperCache infrastructure.

This module provides dedicated caching of complete Team objects (38 fields) using the
existing HyperCache system which handles Redis + S3 backup automatically.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from django.db import transaction

from posthog.models.team.team import Team
from posthog.storage.hypercache import HyperCache, HyperCacheStoreMissing, KeyType

logger = logging.getLogger(__name__)

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

            # Ensure related objects are loaded - check if we need to refetch
            if not hasattr(team, "_state") or not team._state.fields_cache.get("organization"):
                team = Team.objects.select_related("organization", "project").get(id=team.id)
            elif not hasattr(team, "_state") or not team._state.fields_cache.get("project"):
                # If only project is missing, fetch it
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
        logger.warning(f"Team not found for key: {team_key}")
        return HyperCacheStoreMissing()

    except Exception:
        logger.exception(f"Error loading team metadata for {team_key}")
        return HyperCacheStoreMissing()


# Create the HyperCache instance for team metadata
team_metadata_hypercache = HyperCache(
    namespace="team_metadata",
    value="full_metadata.json",
    token_based=True,  # Use team API token as primary key
    load_fn=_load_team_metadata,
    cache_ttl=60 * 60 * 24 * 7,  # 7 days TTL
    cache_miss_ttl=60 * 60 * 24,  # 1 day for missing teams
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
        team_key = team.api_token if isinstance(team, Team) else team
        logger.info(f"Updated metadata cache for team {team_key}")
    else:
        logger.warning(f"Failed to update metadata cache for team {team}")

    return success


def clear_team_metadata_cache(team: Team | str | int, kinds: list[str] | None = None) -> None:
    """
    Clear the metadata cache for a team.

    Args:
        team: Team object, API token string, or team ID
        kinds: Optional list of cache types to clear (["redis", "s3"])
    """
    team_metadata_hypercache.clear_cache(team, kinds=kinds)

    team_key = team.api_token if isinstance(team, Team) else team
    logger.info(f"Cleared metadata cache for team {team_key}")


# Note: Django signals are registered in posthog/tasks/team_metadata.py to avoid circular imports
