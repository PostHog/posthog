import uuid
from datetime import datetime, timedelta
from time import sleep
from typing import List, Optional

import structlog
from celery import group

from posthog import settings
from posthog.celery import app
from posthog.email import EmailMessage
from posthog.models.dashboard import Dashboard
from posthog.models.dashboard_tile import DashboardTile
from posthog.models.exported_asset import ExportedAsset
from posthog.models.subscription import Subscription, get_unsubscribe_token
from posthog.tasks.exporter import export_task

logger = structlog.get_logger(__name__)


def get_unsubscribe_url(subscription: Subscription, email: str) -> str:
    return f"{settings.SITE_URL}/unsubscribe?token={get_unsubscribe_token(subscription, email)}"


def get_tiles_ordered_by_position(dashboard: Dashboard):
    tiles = list(
        DashboardTile.objects.filter(dashboard=dashboard)
        .select_related("insight__created_by", "insight__last_modified_by", "insight__team__organization")
        .prefetch_related("insight__dashboards__team__organization")
        .order_by("insight__order")
        .all()
    )

    return tiles.sort(key=lambda x: x.get("xs", {}).get("y", 100))


def send_email_subscription_report(
    email: str, subscription: Subscription, assets: List[ExportedAsset], invite_message: Optional[str] = None
) -> None:
    inviter = subscription.created_by
    is_invite = invite_message is not None
    self_invite = inviter.email == email

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
        if self_invite:
            subject = f"You have been subscribed to a PostHog {resource_noun}"
        else:
            subject = f"{inviter.first_name or 'Someone'} subscribed you to a PostHog {resource_noun}"
        campaign_key = f"{resource_noun.lower()}_subscription_new_{uuid.uuid4()}"

    message = EmailMessage(
        campaign_key=campaign_key,
        subject=subject,
        template_name="subscription_report",
        template_context={
            "images": [x.get_public_content_url() for x in assets],
            "resource_noun": resource_noun,
            "resource_name": resource_name,
            "resource_url": resource_url,
            "subscription_url": subscription.url,
            "unsubscribe_url": get_unsubscribe_url(subscription=subscription, email=email),
            "inviter": inviter if is_invite else None,
            "self_invite": self_invite,
            "invite_message": invite_message,
        },
    )
    message.add_recipient(email=email)
    message.send()


def _deliver_subscription_report(
    subscription_id: int, new_emails: Optional[List[str]] = None, invite_message: Optional[str] = None
) -> None:
    is_invite = new_emails is not None

    if is_invite and not new_emails:
        return

    subscription = (
        Subscription.objects.prefetch_related("dashboard__insights")
        .select_related("created_by", "insight", "dashboard",)
        .get(pk=subscription_id)
    )

    if subscription.target_type == "email":
        insights = []
        assets = []

        if subscription.dashboard:
            tiles = get_tiles_ordered_by_position(subscription.dashboard)

            for tile in tiles[:6]:
                insights.append(tile.insight)
        elif subscription.insight:
            insights = [subscription.insight]
        else:
            raise Exception("There are no insights to be sent for this Subscription")

        tasks = []
        for insight in insights:
            asset = ExportedAsset.objects.create(team=subscription.team, export_format="image/png", insight=insight)

            tasks.append(export_task.s(asset.id))
            assets.append(asset)

        parallel_job = group(tasks).apply_async()

        max_wait = 30
        while not parallel_job.ready():
            max_wait = max_wait - 1
            sleep(1)
            if max_wait < 0:
                raise Exception("Timed out waiting for exports")

        emails_to_send = new_emails or subscription.target_value.split(",")

        for email in emails_to_send:
            try:
                send_email_subscription_report(
                    email, subscription, assets, invite_message=invite_message or "" if is_invite else None
                )
            except Exception as e:
                logger.error(e)
                raise e
    else:
        raise NotImplementedError(f"{subscription.target_type} is not supported")

    if not is_invite:
        subscription.set_next_delivery_date(subscription.next_delivery_date)
        subscription.save()


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
    return _deliver_subscription_report(subscription_id)


@app.task()
def deliver_new_subscription(subscription_id: int, new_emails: List[str], invite_message: Optional[str] = None) -> None:
    if not new_emails:
        return
    return _deliver_subscription_report(subscription_id, new_emails, invite_message)
