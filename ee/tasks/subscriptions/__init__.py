import structlog
import posthoganalytics
from temporalio import activity, workflow
from temporalio.common import MetricCounter, MetricMeter

from posthog.models.subscription import Subscription

logger = structlog.get_logger(__name__)

# Slack errors that are user configuration issues, not system failures
SLACK_USER_CONFIG_ERRORS = frozenset(
    ["not_in_channel", "account_inactive", "is_archived", "channel_not_found", "invalid_auth"]
)


# Temporal metrics for temporal workers
def get_metric_meter() -> MetricMeter:
    """Get metric meter for the current context (activity or workflow)."""
    if activity.in_activity():
        return activity.metric_meter()
    elif workflow.in_workflow():
        return workflow.metric_meter()
    else:
        raise RuntimeError("Not within workflow or activity context")


def get_subscription_queued_metric(destination: str, execution_path: str) -> MetricCounter:
    return (
        get_metric_meter()
        .with_additional_attributes({"destination": destination, "execution_path": execution_path})
        .create_counter(
            "subscription_queued",
            "A subscription was queued for delivery",
        )
    )


def get_subscription_success_metric(destination: str, execution_path: str) -> MetricCounter:
    return (
        get_metric_meter()
        .with_additional_attributes({"destination": destination, "execution_path": execution_path})
        .create_counter(
            "subscription_send_success",
            "A subscription was sent successfully",
        )
    )


def get_subscription_failure_metric(
    destination: str, execution_path: str, failure_type: str = "complete"
) -> MetricCounter:
    return (
        get_metric_meter()
        .with_additional_attributes(
            {"destination": destination, "execution_path": execution_path, "failure_type": failure_type}
        )
        .create_counter(
            "subscription_send_failure",
            "A subscription failed to send",
        )
    )


SUPPORTED_TARGET_TYPES = frozenset(["email", "slack"])


def _capture_delivery_failed_event(subscription: Subscription, e: Exception) -> None:
    distinct_id = (subscription.created_by.distinct_id if subscription.created_by else None) or subscription.team_id
    posthoganalytics.capture(
        distinct_id=str(distinct_id),
        event="subscription_delivery_failed",
        properties={
            "subscription_id": subscription.id,
            "team_id": subscription.team_id,
            "target_type": subscription.target_type,
            "exception": str(e),
            "exception_type": type(e).__name__,
        },
    )
