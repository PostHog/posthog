import uuid
from urllib.parse import urlparse

from django.utils.formats import date_format

from posthog.email import EmailMessage

from products.exports.backend.models.subscription import Subscription
from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    TargetType,
    create_notification,
    has_been_dispatched,
)
from products.notifications.backend.facade.enums import NotificationOnlyResourceType


def _can_notify_creator(subscription: Subscription) -> bool:
    return (
        subscription.created_by is not None
        and subscription.team.all_users_with_access().filter(id=subscription.created_by_id).exists()
    )


def send_subscription_delivery_failure_email(subscription: Subscription, failure_id: str | None = None) -> None:
    if not _can_notify_creator(subscription) or not subscription.created_by.email:
        return

    title = subscription.title or "your subscription"
    subject = (
        f'PostHog subscription "{subscription.title}" could not be delivered'
        if subscription.title
        else "Your PostHog subscription could not be delivered"
    )
    message = EmailMessage(
        campaign_key=f"subscription-delivery-failed-notification-{failure_id or uuid.uuid4()}",
        subject=subject,
        template_name="subscription_delivery_failed",
        template_context={
            "scheduled_at": subscription.next_delivery_date,
            "subscription_title": title,
            "subscription_url": subscription.url,
        },
    )
    message.add_recipient(email=subscription.created_by.email)
    message.send()


def create_subscription_delivery_failure_notification(
    subscription: Subscription, failure_id: str | None = None
) -> None:
    if not _can_notify_creator(subscription):
        return

    source_id = failure_id or str(uuid.uuid4())
    if has_been_dispatched(
        notification_type=NotificationType.PIPELINE_FAILURE,
        target_type=TargetType.USER,
        target_id=str(subscription.created_by_id),
        resource_id=str(subscription.id),
        source_id=source_id,
    ):
        return

    title = subscription.title or "Subscription"
    notification_title = f"{title[:75]} could not be delivered"
    scheduled_at = date_format(subscription.next_delivery_date, "F j, Y, P T")
    source_url = urlparse(subscription.url).path if subscription.url else ""
    create_notification(
        NotificationData(
            team_id=subscription.team_id,
            notification_type=NotificationType.PIPELINE_FAILURE,
            priority=Priority.NORMAL,
            title=notification_title,
            body=(
                f"PostHog could not deliver this subscription scheduled for {scheduled_at}. "
                "We will try again at its next scheduled delivery."
            ),
            target_type=TargetType.USER,
            target_id=str(subscription.created_by.id),
            resource_type=NotificationOnlyResourceType.PIPELINE,
            resource_id=str(subscription.id),
            source_url=source_url,
            source_id=source_id,
        )
    )
