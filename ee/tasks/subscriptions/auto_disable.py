import uuid

import structlog

from posthog.email import EmailMessage
from posthog.exceptions_capture import capture_exception
from posthog.models.subscription import Subscription

from ee.tasks.subscriptions import SUPPORTED_TARGET_TYPES

# User-visible reasons embedded in the disabled-subscription email body.
SLACK_INTEGRATION_DISCONNECTED_REASON = "Slack integration disconnected"
UNSUPPORTED_TARGET_TYPE_REASON = "Unsupported delivery channel"

logger = structlog.get_logger(__name__)


def validate_re_enable(target_type: str | None, integration_id: int | None) -> str | None:
    """Validate that a subscription with this target configuration can be re-enabled.
    Returns None when re-enable is OK, or a user-facing error message when it would
    fail (rejected up-front so the next delivery doesn't just auto-disable again).
    Mirrors the `validate_alert_config` pattern in posthog.tasks.alerts.utils.
    """
    # Defer to downstream serializer validation when target_type is missing — this
    # function only encodes the "what makes a target type permanently broken" rules.
    if not target_type:
        return None
    if target_type not in SUPPORTED_TARGET_TYPES:
        return (
            f"Cannot re-enable {target_type} subscription: this delivery channel is not currently supported. "
            "Switch to email or Slack."
        )
    if target_type == Subscription.SubscriptionTarget.SLACK and not integration_id:
        return "Cannot re-enable Slack subscription: no integration configured. Reconnect Slack first."
    return None


def disable_invalid_subscription(subscription: Subscription, reason: str) -> None:
    logger.warning(
        "subscription.auto_disabling",
        subscription_id=subscription.id,
        team_id=subscription.team_id,
        reason=reason,
    )
    Subscription.objects.filter(pk=subscription.pk).update(enabled=False)
    # Mirror the UPDATE in memory so callers see the new state without a fresh
    # SELECT — refresh_from_db() would also drop the eagerly-loaded created_by
    # relation (loaded via select_related at the activity site).
    subscription.enabled = False

    if subscription.created_by and subscription.created_by.email:
        try:
            send_notifications_for_disabled_subscription(subscription, reason, [subscription.created_by.email])
        except Exception as e:
            # Disabling is the durable side effect; email is best-effort. If the email
            # fails (SMTP outage, ImproperlyConfigured on self-hosted, Customer.io 5xx)
            # the SLO outcome must stay `success` — we successfully prevented the
            # subscription from re-firing, which is the contract this code provides.
            capture_exception(e)
            logger.warning(
                "subscription.send_disabled_notification_failed",
                subscription_id=subscription.id,
                error=str(e),
                exc_info=True,
            )


def send_notifications_for_disabled_subscription(subscription: Subscription, reason: str, targets: list[str]) -> None:
    logger.info(
        "subscription.send_disabled_notification",
        subscription_id=subscription.id,
        recipient_count=len(targets),
    )

    display_name = subscription.title or "your subscription"
    subject = (
        f'PostHog subscription "{subscription.title}" has been automatically disabled'
        if subscription.title
        else "Your PostHog subscription has been automatically disabled"
    )
    campaign_key = f"subscription-disabled-notification-{subscription.id}-{uuid.uuid4()}"

    message = EmailMessage(
        campaign_key=campaign_key,
        subject=subject,
        template_name="subscription_disabled",
        template_context={
            "subscription_url": subscription.url,
            "subscription_title": display_name,
            "reason": reason,
        },
    )
    for target in targets:
        message.add_recipient(email=target)

    message.send()
