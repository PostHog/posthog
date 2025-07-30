import json
import time
from typing import Optional, Any

import requests
import structlog
from django.conf import settings

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.codec import EncryptionCodec

logger = structlog.get_logger(__name__)

# Webhook request timeout in seconds
WEBHOOK_TIMEOUT = 30

# Maximum retries for failed webhook requests
MAX_RETRIES = 2

# Retry delay in seconds (exponential backoff)
RETRY_DELAY = 2


def _redact_value(value: str) -> str:
    if not value or len(value) <= 3:
        return "*" * len(value) if value else ""

    return value[:3] + "*" * (len(value) - 3)


def decrypt_webhook_headers(encrypted_headers: Optional[dict[str, str]], redact: bool = False) -> dict[str, str]:
    """
    Decrypt webhook headers that were encrypted during storage.

    Args:
        encrypted_headers: Dictionary of encrypted header values

    Returns:
        Dictionary of decrypted header values
    """
    if not encrypted_headers or not isinstance(encrypted_headers, dict):
        return {}

    codec = EncryptionCodec(settings)
    decrypted_headers = {}

    for key, value in encrypted_headers.items():
        if isinstance(value, str):
            try:
                # Try to decrypt the value
                decrypted_value = codec.decrypt(value.encode("utf-8")).decode("utf-8")
                decrypted_headers[key] = decrypted_value if redact is False else _redact_value(decrypted_value)
            except Exception as e:
                logger.warning(
                    "Failed to decrypt webhook header, using as-is",
                    header_key=key,
                    error=str(e),
                )
                # If decryption fails, use the value as-is (might not be encrypted)
                decrypted_headers[key] = value
        else:
            # Non-string values are not encrypted, use as-is
            decrypted_headers[key] = value

    return decrypted_headers


def send_feature_flag_webhook(
    webhook_url: str, payload: dict[str, Any], custom_headers: Optional[dict[str, str]] = None, retry_count: int = 0
) -> bool:
    """
    Send a webhook notification for feature flag changes.

    Args:
        webhook_url: The URL to send the webhook to
        payload: The JSON payload containing feature flag data
        custom_headers: Optional custom headers to include in the request
        retry_count: Current retry attempt (used for exponential backoff)

    Returns:
        bool: True if webhook was sent successfully, False otherwise
    """
    try:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": f"PostHog-Webhooks/{getattr(settings, 'VERSION', '1.0')}",
            "X-PostHog-Event": "feature_flag_changed",
        }

        # Add custom headers if provided (decrypt them first)
        if custom_headers:
            decrypted_headers = decrypt_webhook_headers(custom_headers)
            headers.update(decrypted_headers)

        logger.info(
            "Sending feature flag webhook",
            webhook_url=webhook_url,
            flag_key=payload.get("flag_key"),
            team_id=payload.get("team_id"),
            retry_count=retry_count,
        )

        response = requests.post(
            webhook_url,
            json=payload,
            headers=headers,
            timeout=WEBHOOK_TIMEOUT,
            verify=True,  # Always verify SSL certificates
        )

        # Consider 2xx status codes as successful
        if 200 <= response.status_code < 300:
            logger.info(
                "Feature flag webhook sent successfully",
                webhook_url=webhook_url,
                flag_key=payload.get("flag_key"),
                status_code=response.status_code,
                retry_count=retry_count,
            )
            return True
        else:
            logger.warning(
                "Feature flag webhook failed with bad status code",
                webhook_url=webhook_url,
                flag_key=payload.get("flag_key"),
                status_code=response.status_code,
                response_text=response.text[:500],  # Limit response text to avoid log spam
                retry_count=retry_count,
            )
            return False

    except requests.exceptions.Timeout:
        logger.warning(
            "Feature flag webhook timed out",
            webhook_url=webhook_url,
            flag_key=payload.get("flag_key"),
            timeout=WEBHOOK_TIMEOUT,
            retry_count=retry_count,
        )
        return False

    except requests.exceptions.ConnectionError as e:
        logger.warning(
            "Feature flag webhook connection error",
            webhook_url=webhook_url,
            flag_key=payload.get("flag_key"),
            error=str(e),
            retry_count=retry_count,
        )
        return False

    except Exception as e:
        logger.exception(
            "Unexpected error sending feature flag webhook",
            webhook_url=webhook_url,
            flag_key=payload.get("flag_key"),
            error=str(e),
            retry_count=retry_count,
        )
        capture_exception(e)
        return False


def send_feature_flag_webhooks_with_retry(
    webhook_subscriptions: list[dict[str, Any]], payload: dict[str, Any], max_retries: int = MAX_RETRIES
) -> None:
    """
    Send webhook notifications to multiple webhook subscriptions with retry logic.

    Args:
        webhook_subscriptions: List of webhook subscription objects (with url and optional headers)
        payload: The JSON payload containing feature flag data
        max_retries: Maximum number of retry attempts per webhook
    """
    if not webhook_subscriptions:
        return

    logger.info(
        "Sending feature flag webhooks",
        webhook_count=len(webhook_subscriptions),
        flag_key=payload.get("flag_key"),
        team_id=payload.get("team_id"),
    )

    for subscription in webhook_subscriptions:
        webhook_url = subscription.get("url")
        custom_headers = subscription.get("headers")

        if not webhook_url or not webhook_url.strip():
            continue

        webhook_url = webhook_url.strip()

        # Validate URL format
        if not (webhook_url.startswith("http://") or webhook_url.startswith("https://")):
            logger.warning(
                "Invalid webhook URL format - skipping",
                webhook_url=webhook_url,
                flag_key=payload.get("flag_key"),
            )
            continue

        success = False
        for retry_count in range(max_retries + 1):  # +1 to include initial attempt
            success = send_feature_flag_webhook(webhook_url, payload, custom_headers, retry_count)
            if success:
                break

            # Don't retry on the last attempt
            if retry_count < max_retries:
                delay = RETRY_DELAY * (2**retry_count)  # Exponential backoff
                logger.info(
                    "Retrying feature flag webhook after delay",
                    webhook_url=webhook_url,
                    flag_key=payload.get("flag_key"),
                    retry_count=retry_count + 1,
                    delay_seconds=delay,
                )
                time.sleep(delay)

        if not success:
            logger.error(
                "Feature flag webhook failed after all retries",
                webhook_url=webhook_url,
                flag_key=payload.get("flag_key"),
                max_retries=max_retries,
            )


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
        payloads = feature_flag._payloads
        if payloads and "true" in payloads:
            try:
                # Try to parse the payload for remote config
                remote_payload = json.loads(payloads["true"])
                payload["remote_config_payload"] = remote_payload
            except (json.JSONDecodeError, KeyError, TypeError):
                # If parsing fails, just include the raw payload
                payload["remote_config_payload"] = payloads.get("true")

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

        # Send webhooks asynchronously using Celery
        try:
            from posthog.tasks.feature_flag_webhooks import send_feature_flag_webhooks_task

            send_feature_flag_webhooks_task.delay(valid_subscriptions, payload)
            logger.info(
                "Feature flag webhook task dispatched",
                flag_key=getattr(feature_flag, "key", "unknown"),
                team_id=getattr(feature_flag, "team_id", "unknown"),
                webhook_count=len(valid_subscriptions),
            )
        except Exception as e:
            # Fallback to synchronous execution if Celery is not available
            logger.warning(
                "Failed to dispatch webhook task, falling back to synchronous execution",
                flag_key=getattr(feature_flag, "key", "unknown"),
                team_id=getattr(feature_flag, "team_id", "unknown"),
                error=str(e),
            )
            send_feature_flag_webhooks_with_retry(valid_subscriptions, payload)

    except Exception as e:
        # Never let webhook errors break the main feature flag operation
        logger.exception(
            "Error in feature flag webhook notification",
            flag_key=getattr(feature_flag, "key", "unknown"),
            team_id=getattr(feature_flag, "team_id", "unknown"),
            error=str(e),
        )
        capture_exception(e)
