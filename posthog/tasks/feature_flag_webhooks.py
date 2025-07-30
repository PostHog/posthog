from typing import Any

from celery import shared_task
from structlog import get_logger

logger = get_logger(__name__)


@shared_task(bind=True, max_retries=3)
def send_feature_flag_webhooks_task(self, webhook_subscriptions: list[dict[str, Any]], payload: dict[str, Any]) -> None:
    """
    Celery task to send feature flag webhooks asynchronously.

    Args:
        webhook_subscriptions: List of webhook subscription objects (with url and optional headers)
        payload: The JSON payload containing feature flag data
    """
    try:
        from posthog.helpers.feature_flag_webhooks import send_feature_flag_webhooks_with_retry

        send_feature_flag_webhooks_with_retry(webhook_subscriptions, payload)
    except Exception as e:
        logger.exception(
            "Error in feature flag webhook task",
            flag_key=payload.get("flag_key"),
            team_id=payload.get("team_id"),
            error=str(e),
        )
        # Retry the task with exponential backoff
        raise self.retry(countdown=60 * (2**self.request.retries))
