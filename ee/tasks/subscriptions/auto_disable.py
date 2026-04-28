from django.utils import timezone

import structlog

from posthog.email import EmailMessage
from posthog.models.subscription import Subscription

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
    subscription.refresh_from_db()

    if subscription.created_by and subscription.created_by.email:
        send_notifications_for_disabled_subscription(subscription, reason, [subscription.created_by.email])


def send_notifications_for_disabled_subscription(subscription: Subscription, reason: str, targets: list[str]) -> None:
    logger.info(
        "subscription.send_disabled_notification",
        subscription_id=subscription.id,
        recipient_count=len(targets),
    )

    if subscription.title:
        subject = f'PostHog subscription "{subscription.title}" has been disabled'
    else:
        subject = "Your PostHog subscription has been disabled"
    title = subscription.title or "your subscription"
    campaign_key = f"subscription-disabled-notification-{subscription.id}-{timezone.now().timestamp()}"

    message = EmailMessage(
        campaign_key=campaign_key,
        subject=subject,
        template_name="subscription_disabled",
        template_context={
            "subscription_url": subscription.url,
            "subscription_title": title,
            "reason": reason,
        },
    )
    for target in targets:
        message.add_recipient(email=target)

    message.send()
