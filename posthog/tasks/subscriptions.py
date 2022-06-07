from datetime import datetime, timedelta

import structlog

from posthog.celery import app
from posthog.models.exported_asset import ExportedAsset
from posthog.models.subscription import Subscription
from posthog.tasks.exporter import export_task

logger = structlog.get_logger(__name__)


@app.task()
def schedule_all_subscriptions() -> None:
    """
    Schedule all past notifications (with a buffer) to be delivered
    """

    now_with_buffer = datetime.utcnow() + timedelta(minutes=15)
    subscriptions = Subscription.objects.filter(next_delivery_date__lte=now_with_buffer).all()

    for subscription in subscriptions:
        deliver_subscription.delay(subscription.id)


@app.task()
def deliver_subscription(subscription_id: int):
    subscription = Subscription.objects.get(pk=subscription_id)

    if subscription.target_type == "email":
        instance = ExportedAsset.objects.create(
            team=subscription.team, insight=subscription.insight, export_format="image/png"
        )
        export_task(instance.id)

        for email in subscription.target_value.split(","):
            # TODO: Send email with embedded image asset
            logger.debug(f"Will send email to {email}")
            continue

        subscription.set_next_delivery_date(subscription.next_delivery_date)
        subscription.save()
    else:
        raise NotImplementedError(f"{subscription.target_type} is not supported")
