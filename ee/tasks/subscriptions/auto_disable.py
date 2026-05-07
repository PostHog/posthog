import uuid
from typing import NamedTuple

import structlog

from posthog.email import EmailMessage
from posthog.exceptions_capture import capture_exception
from posthog.models.subscription import Subscription

from ee.tasks.subscriptions import SUPPORTED_TARGET_TYPES


class DisableReason(NamedTuple):
    # Stable identity used for analytics (`error_type`) and activity comparisons.
    key: str
    # Shown in the disabled-subscription email body and the activity's recipient_results.
    description: str
    # Re-enable rejection message surfaced by the API serializer; `{target_type}` is interpolated.
    user_message: str


SLACK_DISCONNECTED_DISABLE_REASON = DisableReason(
    key="missing_integration",
    description="Slack integration disconnected",
    user_message="Cannot re-enable Slack subscription: no integration configured. Reconnect Slack first.",
)
UNSUPPORTED_TARGET_DISABLE_REASON = DisableReason(
    key="unsupported_target",
    description="Unsupported delivery channel",
    user_message="Cannot re-enable {target_type} subscription: this delivery channel is not currently supported.",
)

logger = structlog.get_logger(__name__)


def get_subscription_disable_reason(target_type: str | None, integration_id: int | None) -> DisableReason | None:
    """Single source of truth for "what target configuration is permanently broken"."""
    if not target_type:
        return None
    if target_type not in SUPPORTED_TARGET_TYPES:
        return UNSUPPORTED_TARGET_DISABLE_REASON
    if target_type == Subscription.SubscriptionTarget.SLACK and not integration_id:
        return SLACK_DISCONNECTED_DISABLE_REASON
    return None


def validate_re_enable(target_type: str | None, integration_id: int | None) -> str | None:
    """API-serializer wrapper — returns the user-facing rejection message, or None if re-enable is OK."""
    reason = get_subscription_disable_reason(target_type, integration_id)
    if reason is None:
        return None
    return reason.user_message.format(target_type=target_type)


def disable_invalid_subscription(subscription: Subscription, reason: DisableReason) -> None:
    # Compare-and-swap so only one racing caller sends the disabled-notification
    # email (UUID4 campaign keys mean MessagingRecord can't dedup the duplicate).
    rowcount = Subscription.objects.filter(pk=subscription.pk, enabled=True).update(enabled=False)
    if rowcount == 0:
        # A concurrent caller already disabled the row — no-op, no side effects.
        # The in-memory `subscription.enabled` is intentionally NOT touched here so
        # callers can distinguish "we just disabled it" from "it was already disabled";
        # the activity site re-fetches via select_related when it needs fresh state.
        logger.info(
            "subscription.auto_disable_already_disabled",
            subscription_id=subscription.id,
            team_id=subscription.team_id,
            reason=reason.key,
        )
        return

    logger.warning(
        "subscription.auto_disabling",
        subscription_id=subscription.id,
        team_id=subscription.team_id,
        reason=reason.key,
    )
    # Mirror the UPDATE in memory so callers see the new state without a fresh
    # SELECT — refresh_from_db() would also drop the eagerly-loaded created_by
    # relation (loaded via select_related at the activity site).
    subscription.enabled = False

    if subscription.created_by and subscription.created_by.email:
        try:
            send_notifications_for_disabled_subscription(
                subscription, reason.description, [subscription.created_by.email]
            )
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
