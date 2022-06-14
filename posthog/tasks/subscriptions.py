import uuid
from datetime import datetime, timedelta
from typing import List, Optional

import structlog

from posthog import settings
from posthog.celery import app
from posthog.email import EmailMessage
from posthog.models.exported_asset import ExportedAsset
from posthog.models.subscription import Subscription, get_unsubscribe_token
from posthog.tasks.exporter import export_task

logger = structlog.get_logger(__name__)


def get_unsubscribe_url(subscription: Subscription, email: str) -> str:
    return f"{settings.SITE_URL}/unsubscribe?token={get_unsubscribe_token(subscription, email)}"


def send_email_subscription_report(
    email: str, subscription: Subscription, exported_asset: ExportedAsset, invite_message: Optional[str] = None
) -> None:
    is_invite = invite_message is not None
    inviter = subscription.created_by
    subject = "Posthog Report"
    resource_noun = None
    resource_url = None

    if subscription.insight:
        resource_name = f"{subscription.insight.name or subscription.insight.derived_name}"
        resource_noun = "Insight"
        resource_url = subscription.insight.url
    elif subscription.dashboard:
        resource_name = subscription.dashboard.name
        resource_noun = "Dashboard"
        resource_url = subscription.dashboard.url
    else:
        raise NotImplementedError()

    subject = f"PostHog {resource_noun} report - {resource_name}"
    campaign_key = f"{resource_noun.lower()}_subscription_report_{subscription.next_delivery_date.isoformat()}"

    if is_invite:
        subject = f"{inviter.first_name} subscribed you to a PostHog Insight"
        campaign_key = f"{resource_noun.lower()}_subscription_new_{uuid.uuid4()}"

    message = EmailMessage(
        campaign_key=campaign_key,
        subject=subject,
        template_name="subscription_report",
        template_context={
            "images": [exported_asset.get_public_content_url()],
            "resource_noun": resource_noun,
            "resource_name": resource_name,
            "resource_url": resource_url,
            "subscription_url": subscription.url,
            "unsubscribe_url": get_unsubscribe_url(subscription=subscription, email=email),
            "inviter": inviter if is_invite else None,
            "invite_message": invite_message,
        },
    )
    message.add_recipient(email=email)
    message.send()


@app.task()
def schedule_all_subscriptions() -> None:
    """
    Schedule all past notifications (with a buffer) to be delivered
    NOTE: This task is scheduled hourly just before the hour allowing for the 15 minute timedelta to cover
    all upcoming hourly scheduled subscriptions
    """

    now_with_buffer = datetime.utcnow() + timedelta(minutes=15)
    subscriptions = Subscription.objects.filter(next_delivery_date__lte=now_with_buffer, deleted=False).all()

    for subscription in subscriptions:
        deliver_subscription_report.delay(subscription.id)


@app.task()
def deliver_subscription_report(subscription_id: int) -> None:
    subscription = Subscription.objects.select_related("created_by", "insight").get(pk=subscription_id)

    if subscription.target_type == "email":
        asset = ExportedAsset.objects.create(
            team=subscription.team, insight=subscription.insight, export_format="image/png"
        )
        export_task(asset.id)

        for email in subscription.target_value.split(","):
            try:
                send_email_subscription_report(email, subscription, asset)
            except Exception as e:
                logger.error(e)
                raise e
    else:
        raise NotImplementedError(f"{subscription.target_type} is not supported")

    subscription.set_next_delivery_date(subscription.next_delivery_date)
    subscription.save()


@app.task()
def deliver_new_subscription(subscription_id: int, new_emails: List[str], invite_message: Optional[str] = None) -> None:
    if not new_emails:
        return
    subscription = Subscription.objects.select_related("created_by", "insight").get(pk=subscription_id)

    if subscription.target_type == "email":
        asset = ExportedAsset.objects.create(
            team=subscription.team, insight=subscription.insight, export_format="image/png"
        )
        export_task(asset.id)

        for email in new_emails:
            try:
                send_email_subscription_report(email, subscription, asset, invite_message=invite_message or "")
            except Exception as e:
                logger.error(e)
                raise e
    else:
        raise NotImplementedError(f"{subscription.target_type} is not supported")
