import json
from typing import Any

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.tasks.feature_flag_webhooks import send_all_feature_flag_webhooks

logger = structlog.get_logger(__name__)


def create_feature_flag_webhook_payload(feature_flag, change_type: str = "updated") -> dict[str, Any]:
    """
    Create the webhook payload for a feature flag change.

    Args:
        feature_flag: The FeatureFlag model instance
        change_type: Type of change ("created", "updated", "deleted")

    Returns:
        Dict containing the webhook payload
    """
    from posthog.models.feature_flag.feature_flag import FeatureFlag
    from django.utils import timezone

    if not isinstance(feature_flag, FeatureFlag):
        logger.error("Invalid feature flag object passed to webhook payload creation")
        return {}

    # Create comprehensive payload for Feature Flag changes
    payload = {
        "event": "feature_flag_changed",
        "change_type": change_type,
        "timestamp": timezone.now().isoformat(),
        "feature_flag": {
            "id": feature_flag.id,
            "key": feature_flag.key,
            "name": feature_flag.name,
            "active": feature_flag.active,
            "deleted": feature_flag.deleted,
            "filters": feature_flag.filters,
            "rollout_percentage": feature_flag.rollout_percentage,
            "version": feature_flag.version,
            "created_at": feature_flag.created_at.isoformat() if feature_flag.created_at else None,
            "last_modified_by": feature_flag.last_modified_by.email if feature_flag.last_modified_by else None,
            "ensure_experience_continuity": feature_flag.ensure_experience_continuity,
            "has_enriched_analytics": feature_flag.has_enriched_analytics,
            "is_remote_configuration": feature_flag.is_remote_configuration,
            "has_encrypted_payloads": feature_flag.has_encrypted_payloads,
        },
        "team": {
            "id": feature_flag.team.id,
            "name": feature_flag.team.name,
            "organization_id": str(feature_flag.team.organization_id),
        },
        "metadata": {
            "variants_count": len(feature_flag.variants),
            "conditions_count": len(feature_flag.conditions),
            "uses_cohorts": feature_flag.uses_cohorts,
            "aggregation_group_type_index": feature_flag.aggregation_group_type_index,
        },
    }

    # Add remote config payload if available and flag is remote config
    if feature_flag.is_remote_configuration:
        ff_payload = feature_flag.get_payload("true")
        if ff_payload:
            try:
                # Try to parse the payload for remote config
                remote_payload = json.loads(ff_payload)
                payload["remote_config_payload"] = remote_payload
            except (json.JSONDecodeError, KeyError, TypeError):
                # If parsing fails, just include the raw payload
                payload["remote_config_payload"] = ff_payload

    return payload


def notify_feature_flag_webhooks(feature_flag, change_type: str = "updated") -> None:
    """
    Main function to notify all webhook subscriptions for a feature flag change.
    This function should be called from Django signal handlers.

    Args:
        feature_flag: The FeatureFlag model instance
        change_type: Type of change ("created", "updated", "deleted")
    """
    try:
        # Get webhook subscriptions from the feature flag
        webhook_subscriptions = feature_flag.webhook_subscriptions or []
        if not webhook_subscriptions or not isinstance(webhook_subscriptions, list):
            logger.debug(
                "No webhook subscriptions found for feature flag",
                flag_key=getattr(feature_flag, "key", "unknown"),
                team_id=getattr(feature_flag, "team_id", "unknown"),
            )
            return

        # Filter out empty/invalid subscriptions
        valid_subscriptions = []
        for sub in webhook_subscriptions:
            url = sub.get("url")
            if url and url.strip():
                valid_subscriptions.append(sub)

        if not valid_subscriptions:
            logger.debug(
                "No valid webhook subscriptions found for feature flag",
                flag_key=getattr(feature_flag, "key", "unknown"),
                team_id=getattr(feature_flag, "team_id", "unknown"),
            )
            return

        # Create the webhook payload
        payload = create_feature_flag_webhook_payload(feature_flag, change_type)
        if not payload:
            logger.error(
                "Failed to create webhook payload for feature flag",
                flag_key=getattr(feature_flag, "key", "unknown"),
                team_id=getattr(feature_flag, "team_id", "unknown"),
            )
            return

        send_all_feature_flag_webhooks(valid_subscriptions, payload)

    except Exception as e:
        # Never let webhook errors break the main feature flag operation
        logger.exception(
            "Error in feature flag webhook notification",
            flag_key=getattr(feature_flag, "key", "unknown"),
            team_id=getattr(feature_flag, "team_id", "unknown"),
            error=str(e),
        )
        capture_exception(e)
