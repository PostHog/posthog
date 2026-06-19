import uuid
from typing import NamedTuple

import structlog

from posthog.email import EmailMessage

from products.exports.backend.models.subscription import Subscription

logger = structlog.get_logger(__name__)


class FailureReason(NamedTuple):
    # One-line, user-facing description of what went wrong.
    summary: str
    # Concrete next step the subscription owner can take. May be empty.
    suggestion: str


GENERIC_FAILURE_REASON = FailureReason(
    summary="PostHog hit an unexpected error while preparing or sending this report.",
    suggestion="We'll automatically retry on the next scheduled run. If it keeps failing, reach out to support and we'll dig in.",
)

SLACK_FAILURE_REASON = FailureReason(
    summary="PostHog couldn't post this report to Slack.",
    suggestion="This is usually a temporary Slack issue, and we'll retry on the next scheduled run. If it keeps failing, check that the PostHog app is still installed in your Slack workspace and is a member of the target channel.",
)

EMAIL_FAILURE_REASON = FailureReason(
    summary="PostHog couldn't deliver this report by email.",
    suggestion="We'll retry on the next scheduled run. If it keeps failing, double-check the recipient email addresses on the subscription.",
)


def classify_delivery_failure(target_type: str | None) -> FailureReason:
    """Map a failed delivery to a user-facing reason + suggestion.

    Deliberately coarse and keyed off the delivery channel: the underlying exception is
    often redacted (it can carry Slack tokens or recipient PII), so we describe what we
    can say honestly rather than surfacing a raw error string to the subscription owner.
    """
    if target_type == Subscription.SubscriptionTarget.SLACK:
        return SLACK_FAILURE_REASON
    if target_type == Subscription.SubscriptionTarget.EMAIL:
        return EMAIL_FAILURE_REASON
    return GENERIC_FAILURE_REASON


def failure_target_label(subscription: Subscription) -> str | None:
    """A human-friendly rendering of where the subscription delivers, for the email body.

    Slack target_value is stored as `channel_id|channel_name`; email target_value is a
    comma-separated list of addresses (which the owner set themselves, so it's safe to echo).
    """
    target_value = (subscription.target_value or "").strip()
    if not target_value:
        return None
    if subscription.target_type == Subscription.SubscriptionTarget.SLACK:
        # Stored as `channel_id|channel_name`; show the name, not the raw id. With no name
        # part we have nothing human-readable, so omit the target rather than print an id.
        _, _, channel_name = target_value.partition("|")
        channel_name = channel_name.strip()
        if not channel_name:
            return None
        return channel_name if channel_name.startswith("#") else f"#{channel_name}"
    return target_value


def send_notification_for_failed_subscription(
    subscription: Subscription,
    reason: FailureReason,
    error_type: str | None,
    delivery_id: uuid.UUID,
    targets: list[str],
) -> None:
    logger.info(
        "subscription.send_failed_notification",
        subscription_id=subscription.id,
        recipient_count=len(targets),
    )

    display_name = subscription.title or "your subscription"
    subject = (
        f'PostHog subscription "{subscription.title}" failed to send'
        if subscription.title
        else "Your PostHog subscription failed to send"
    )
    # Keyed on the failed delivery, not a fresh uuid: a Temporal activity retry (worker
    # crash/timeout) then reuses the same key, so MessagingRecord dedups the duplicate
    # send. Distinct failures still differ — each delivery attempt has its own id.
    campaign_key = f"subscription-failed-notification-{delivery_id}"

    message = EmailMessage(
        campaign_key=campaign_key,
        subject=subject,
        template_name="subscription_failed",
        template_context={
            "subscription_url": subscription.url,
            "subscription_title": display_name,
            "target_label": failure_target_label(subscription),
            "failure_summary": reason.summary,
            "failure_suggestion": reason.suggestion,
            "error_type": error_type,
        },
    )
    for target in targets:
        message.add_recipient(email=target)

    message.send()
