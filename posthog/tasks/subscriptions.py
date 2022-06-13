import uuid
from datetime import datetime, timedelta
from typing import List
from requests import delete

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


def send_email_subscription_report(email: str, subscription: Subscription, exported_asset: ExportedAsset) -> None:
    message = EmailMessage(
        campaign_key=f"insight_subscription_report_{subscription.next_delivery_date.isoformat()}",
        subject=f"PostHog Insight report - {subscription.insight.name or subscription.insight.derived_name}",
        template_name="insight_subscription_report",
        template_context={
            "exported_asset": exported_asset,
            "subscription": subscription,
            "unsubscribe_url": get_unsubscribe_url(subscription=subscription, email=email),
        },
    )
    message.add_recipient(email=email)
    message.send()


def send_email_new_subscription(email: str, subscription: Subscription, exported_asset: ExportedAsset) -> None:
    inviter = subscription.created_by
    message = EmailMessage(
        campaign_key=f"insight_subscription_new_{uuid.uuid4()}",
        subject=f"{inviter.first_name} subscribed you to a PostHog Insight",
        template_name="insight_subscription_report",
        template_context={
            "exported_asset": exported_asset,
            "subscription": subscription,
            "unsubscribe_url": get_unsubscribe_url(subscription=subscription, email=email),
            "inviter": inviter,
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
def deliver_new_subscription(subscription_id: int, new_emails: List[str]) -> None:
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
                send_email_new_subscription(email, subscription, asset)
            except Exception as e:
                logger.error(e)
                raise e
    else:
        raise NotImplementedError(f"{subscription.target_type} is not supported")

    subscription.save()
