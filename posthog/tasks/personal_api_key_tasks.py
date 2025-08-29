"""
Background tasks for updating personal API key usage tracking.

This module provides Celery tasks to update personal API key last_used_at
timestamps in a resilient manner that doesn't block authentication flows.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from django.core.exceptions import ObjectDoesNotExist
from django.db import OperationalError, transaction
from django.utils import timezone

from celery import shared_task
from prometheus_client import Counter

logger = logging.getLogger(__name__)

# Prometheus metrics
PERSONAL_API_KEY_USAGE_UPDATES = Counter(
    "posthog_personal_api_key_usage_updates_total",
    "Number of personal API key usage update operations",
    labelnames=["result"],
)


@shared_task(ignore_result=True, max_retries=0)
def update_personal_api_key_last_used(personal_api_key_id: str, timestamp_iso: str) -> None:
    """
    Update the last_used_at timestamp for a personal API key.

    This task uses a fail-fast approach with no retries. If it fails due to
    database connectivity or other issues, it logs the failure and relies on
    the next authentication request to try again.

    Args:
        personal_api_key_id: The ID of the PersonalAPIKey to update
        timestamp_iso: ISO format timestamp string for when the key was used

    Note:
        - No retries to avoid out-of-order updates from delayed tasks
        - Only updates if more than 1 hour has passed since last update
        - Fails fast on any error and logs for monitoring
    """

    try:
        # Parse the timestamp
        try:
            usage_timestamp = datetime.fromisoformat(timestamp_iso.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            logger.warning(f"Invalid timestamp format in update_personal_api_key_last_used: {timestamp_iso}")
            PERSONAL_API_KEY_USAGE_UPDATES.labels(result="invalid_timestamp").inc()
            return

        # Import here to avoid circular imports
        from posthog.models.personal_api_key import PersonalAPIKey

        with transaction.atomic():
            try:
                # Get the personal API key with select_for_update to prevent race conditions
                personal_api_key = PersonalAPIKey.objects.select_for_update().get(id=personal_api_key_id)
            except ObjectDoesNotExist:
                # Key was deleted - this is expected behavior, not an error
                logger.debug(f"PersonalAPIKey {personal_api_key_id} no longer exists")
                PERSONAL_API_KEY_USAGE_UPDATES.labels(result="key_not_found").inc()
                return

            # Check if we need to update (same logic as PersonalAPIKeyAuthentication)
            # Only update if the hour has changed to avoid excessive UPDATE queries
            key_last_used_at = personal_api_key.last_used_at
            if key_last_used_at is None or (usage_timestamp - key_last_used_at > timedelta(hours=1)):
                personal_api_key.last_used_at = usage_timestamp
                personal_api_key.save(update_fields=["last_used_at"])

                logger.debug(
                    f"Updated last_used_at for PersonalAPIKey {personal_api_key_id}",
                    extra={
                        "personal_api_key_id": personal_api_key_id,
                        "timestamp": usage_timestamp.isoformat(),
                        "previous_last_used_at": key_last_used_at.isoformat() if key_last_used_at else None,
                    },
                )
                PERSONAL_API_KEY_USAGE_UPDATES.labels(result="updated").inc()
            else:
                logger.debug(
                    f"Skipped update for PersonalAPIKey {personal_api_key_id} - less than 1 hour since last update",
                    extra={
                        "personal_api_key_id": personal_api_key_id,
                        "timestamp": usage_timestamp.isoformat(),
                        "last_used_at": key_last_used_at.isoformat(),
                    },
                )
                PERSONAL_API_KEY_USAGE_UPDATES.labels(result="skipped_recent").inc()

    except OperationalError as e:
        # Database connectivity issue - log and fail fast
        logger.warning(
            f"Database error updating PersonalAPIKey {personal_api_key_id} last_used_at: {e}",
            extra={
                "personal_api_key_id": personal_api_key_id,
                "timestamp": timestamp_iso,
                "error_type": "database_error",
            },
        )
        PERSONAL_API_KEY_USAGE_UPDATES.labels(result="database_error").inc()

    except Exception as e:
        # Unexpected error - log and fail fast
        logger.error(
            f"Unexpected error updating PersonalAPIKey {personal_api_key_id} last_used_at: {e}",
            extra={
                "personal_api_key_id": personal_api_key_id,
                "timestamp": timestamp_iso,
                "error_type": e.__class__.__name__,
            },
            exc_info=True,
        )
        PERSONAL_API_KEY_USAGE_UPDATES.labels(result="unexpected_error").inc()


def schedule_personal_api_key_usage_update(personal_api_key_id: str, timestamp: Optional[datetime] = None) -> bool:
    """
    Schedule a task to update personal API key usage timestamp.

    This is a helper function that can be called from authentication flows
    to schedule the background update task.

    Args:
        personal_api_key_id: The ID of the PersonalAPIKey to update
        timestamp: When the key was used (defaults to now)

    Returns:
        True if task was scheduled successfully, False otherwise

    Note:
        This function never raises exceptions - it logs failures and returns False
    """
    try:
        if timestamp is None:
            timestamp = timezone.now()

        # Convert to ISO format for task serialization
        timestamp_iso = timestamp.isoformat()

        # Schedule the task
        update_personal_api_key_last_used.delay(personal_api_key_id, timestamp_iso)

        logger.debug(
            f"Scheduled usage update for PersonalAPIKey {personal_api_key_id}",
            extra={
                "personal_api_key_id": personal_api_key_id,
                "timestamp": timestamp_iso,
            },
        )
        return True

    except Exception as e:
        # Task scheduling failed - log but don't raise
        logger.warning(
            f"Failed to schedule usage update for PersonalAPIKey {personal_api_key_id}: {e}",
            extra={
                "personal_api_key_id": personal_api_key_id,
                "error_type": e.__class__.__name__,
            },
        )
        return False
