import structlog

from posthog.email import EmailMessage
from posthog.exceptions_capture import capture_exception
from posthog.models.subscription import Subscription

# User-visible reasons embedded in the disabled-subscription email body.
SLACK_INTEGRATION_DISCONNECTED_REASON = "Slack integration disconnected"
UNSUPPORTED_TARGET_TYPE_REASON = "Unsupported delivery channel"
NO_ASSETS_REASON = "All insights or dashboard tiles for this subscription have been deleted"

logger = structlog.get_logger(__name__)


def disable_invalid_subscription(subscription: Subscription, reason: str) -> None:
    """Auto-disable a subscription whose delivery prerequisite is permanently invalid.

    Called from the Temporal delivery activity when we detect that the subscription
    cannot succeed without user intervention (e.g. the Slack integration was
    disconnected). Mirrors `posthog.tasks.alerts.utils.disable_invalid_alert`.
    """
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
            )


def send_notifications_for_disabled_subscription(subscription: Subscription, reason: str, targets: list[str]) -> None:
    logger.info(
        "subscription.send_disabled_notification",
        subscription_id=subscription.id,
        recipient_count=len(targets),
    )

    display_name = subscription.title or "your subscription"
    subject = (
        f'PostHog subscription "{subscription.title}" has been disabled'
        if subscription.title
        else "Your PostHog subscription has been disabled"
    )
    # Deterministic key — `MessagingRecord` dedupes on this campaign_key per recipient,
    # so retries (Temporal, concurrent workflows, rolling deploys) don't double-send.
    campaign_key = f"subscription-disabled-notification-{subscription.id}"

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
