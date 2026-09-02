import uuid
from urllib.parse import urlparse

from django.utils.formats import date_format

from posthog.email import EmailMessage
from posthog.models import User

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


def _get_notification_creator(subscription: Subscription) -> User | None:
    creator = subscription.created_by
    creator_id = subscription.created_by_id
    if creator is None or creator_id is None:
        return None
    if not subscription.team.all_users_with_access().filter(id=creator_id).exists():
        return None
    return creator


def send_subscription_delivery_failure_email(subscription: Subscription, failure_id: str | None = None) -> None:
    creator = _get_notification_creator(subscription)
    if creator is None or not creator.email:
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
    message.add_recipient(email=creator.email)
    message.send()


def create_subscription_delivery_failure_notification(
    subscription: Subscription, failure_id: str | None = None
) -> None:
    creator = _get_notification_creator(subscription)
    if creator is None:
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
    scheduled_at = (
        date_format(subscription.next_delivery_date, "F j, Y, P T")
        if subscription.next_delivery_date is not None
        else "an upcoming time"
    )
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
            target_id=str(creator.id),
            resource_type=NotificationOnlyResourceType.PIPELINE,
            resource_id=str(subscription.id),
            source_url=source_url,
            source_id=source_id,
        )
    )
