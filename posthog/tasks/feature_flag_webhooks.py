from typing import Any, Optional

import requests
from celery import shared_task
from celery.exceptions import Retry
from django.conf import settings
from structlog import get_logger

from posthog.exceptions_capture import capture_exception
from posthog.helpers.encrypted_flag_payloads import decrypt_webhook_headers

logger = get_logger(__name__)

# Retry delay in seconds (exponential backoff)
RETRY_DELAY = 2

# Webhook request timeout in seconds
WEBHOOK_TIMEOUT = 30

# Maximum retries for failed webhook requests
MAX_RETRIES = 2


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
            flag_key=payload.get("feature_flag", {}).get("key"),
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
                flag_key=payload.get("feature_flag", {}).get("key"),
                status_code=response.status_code,
                retry_count=retry_count,
            )
            return True
        else:
            logger.warning(
                "Feature flag webhook failed with bad status code",
                webhook_url=webhook_url,
                flag_key=payload.get("feature_flag", {}).get("key"),
                status_code=response.status_code,
                response_text=response.text[:500],  # Limit response text to avoid log spam
                retry_count=retry_count,
            )
            return False

    except requests.exceptions.Timeout:
        logger.warning(
            "Feature flag webhook timed out",
            webhook_url=webhook_url,
            flag_key=payload.get("feature_flag", {}).get("key"),
            timeout=WEBHOOK_TIMEOUT,
            retry_count=retry_count,
        )
        return False

    except requests.exceptions.ConnectionError as e:
        logger.warning(
            "Feature flag webhook connection error",
            webhook_url=webhook_url,
            flag_key=payload.get("feature_flag", {}).get("key"),
            error=str(e),
            retry_count=retry_count,
        )
        return False

    except Exception as e:
        logger.exception(
            "Unexpected error sending feature flag webhook",
            webhook_url=webhook_url,
            flag_key=payload.get("feature_flag", {}).get("key"),
            error=str(e),
            retry_count=retry_count,
        )
        capture_exception(e)
        return False


def send_all_feature_flag_webhooks(webhook_subscriptions: list[dict[str, Any]], payload: dict[str, Any]) -> None:
    """
    Dispatches tasks to send webhook notifications to all feature flag subscriptions

    Args:
        webhook_subscriptions: List of webhook subscription objects (with url and optional headers)
        payload: The JSON payload containing feature flag data
    """
    if not webhook_subscriptions:
        return

    logger.info(
        "Dispatching feature flag webhooks as individual tasks",
        webhook_count=len(webhook_subscriptions),
        flag_key=payload.get("feature_flag", {}).get("key"),
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
                flag_key=payload.get("feature_flag", {}).get("key"),
            )
            continue

        try:
            # Dispatches async Celery task
            send_single_feature_flag_webhook_task.delay(
                webhook_url=webhook_url,
                payload=payload,
                custom_headers=custom_headers or {},
            )

            logger.info(
                "Feature flag webhook task dispatched",
                webhook_url=webhook_url,
                flag_key=payload.get("feature_flag", {}).get("key"),
            )
        except Exception as e:
            logger.exception(
                "Failed to dispatch webhook task, attempting synchronous fallback",
                webhook_url=webhook_url,
                flag_key=payload.get("feature_flag", {}).get("key"),
                error=str(e),
            )
            # Fallback to synchronous execution (single attempt, no retry)
            send_feature_flag_webhook(
                webhook_url=webhook_url,
                payload=payload,
                custom_headers=custom_headers,
                retry_count=0,
            )


@shared_task(bind=True, max_retries=MAX_RETRIES)
def send_single_feature_flag_webhook_task(
    self, webhook_url: str, payload: dict[str, Any], custom_headers: dict[str, str] | None = None
) -> None:
    """
    Celery task to send a single feature flag webhook with retry logic.

    Args:
        webhook_url: The URL to send the webhook to
        payload: The JSON payload containing feature flag data
        custom_headers: Optional custom headers to include in the request
    """
    try:
        success = send_feature_flag_webhook(
            webhook_url=webhook_url,
            payload=payload,
            custom_headers=custom_headers,
            retry_count=self.request.retries,
        )

        if not success:
            # Webhook failed, let Celery handle the retry with exponential backoff
            delay = RETRY_DELAY * (2**self.request.retries)
            logger.info(
                "Retrying feature flag webhook via Celery",
                webhook_url=webhook_url,
                flag_key=payload.get("feature_flag", {}).get("key"),
                retry_count=self.request.retries + 1,
                delay_seconds=delay,
            )
            raise self.retry(countdown=delay)

    except Retry:
        # Re-raise Retry exceptions to let Celery handle them
        raise
    except Exception as e:
        logger.exception(
            "Error in single webhook task",
            webhook_url=webhook_url,
            flag_key=payload.get("feature_flag", {}).get("key"),
            error=str(e),
        )
        # For unexpected errors, also retry with exponential backoff
        delay = RETRY_DELAY * (2**self.request.retries)
        raise self.retry(countdown=delay)
