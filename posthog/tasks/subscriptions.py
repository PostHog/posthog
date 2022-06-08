from datetime import datetime, timedelta

import structlog

from posthog import settings
from posthog.celery import app
from posthog.email import EmailMessage
from posthog.models.exported_asset import ExportedAsset
from posthog.models.subscription import Subscription
from posthog.tasks.exporter import export_task

logger = structlog.get_logger(__name__)


def get_unsubscribe_url(subscription: Subscription, email: str):
    # TODO: Do some funky JWT encoding here
    return f"{settings.SITE_URL}/unsubscribe?email={email}&subscription={subscription.id}"


def send_email_subscription(email: str, subscription: Subscription, exported_asset: ExportedAsset) -> None:
    inviter = subscription.created_by

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


@app.task()
def schedule_all_subscriptions() -> None:
    """
    Schedule all past notifications (with a buffer) to be delivered
    NOTE: This task is scheduled hourly 10 minutes before the hour allowing for the 15 minute timedelta to cover
    all upcoming hourly scheduled subscriptions
    """

    now_with_buffer = datetime.utcnow() + timedelta(minutes=15)
    subscriptions = Subscription.objects.filter(next_delivery_date__lte=now_with_buffer).all()

    for subscription in subscriptions:
        deliver_subscription.delay(subscription.id)


@app.task()
def deliver_subscription(subscription_id: int):
    subscription = Subscription.objects.select_related("created_by", "insight").get(pk=subscription_id)

    if subscription.target_type == "email":
        asset = ExportedAsset.objects.create(
            team=subscription.team, insight=subscription.insight, export_format="image/png"
        )
        export_task(asset.id)

        for email in subscription.target_value.split(","):
            try:
                send_email_subscription(email, subscription, asset)
            except Exception as e:
                logger.error(e)
                raise e
    else:
        raise NotImplementedError(f"{subscription.target_type} is not supported")

    subscription.set_next_delivery_date(subscription.next_delivery_date)
    subscription.save()
