from datetime import datetime, timedelta
from itertools import groupby
from typing import Optional

import structlog
import posthoganalytics
from celery import shared_task
from prometheus_client import Counter

from posthog import settings
from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.models.subscription import Subscription
from posthog.sync import database_sync_to_async
from posthog.tasks.utils import CeleryQueue

from ee.tasks.subscriptions.email_subscriptions import send_email_subscription_report
from ee.tasks.subscriptions.slack_subscriptions import (
    get_slack_integration_for_team,
    send_slack_message_with_integration_async,
    send_slack_subscription_report,
)
from ee.tasks.subscriptions.subscription_utils import generate_assets, generate_assets_async

logger = structlog.get_logger(__name__)

SUBSCRIPTION_QUEUED = Counter(
    "subscription_queued",
    "A subscription was queued for delivery",
    labelnames=["destination", "execution_path"],
)
SUBSCRIPTION_SUCCESS = Counter(
    "subscription_send_success",
    "A subscription was sent successfully",
    labelnames=["destination", "execution_path"],
)
SUBSCRIPTION_FAILURE = Counter(
    "subscription_send_failure",
    "A subscription failed to send",
    labelnames=["destination", "execution_path"],
)


async def deliver_subscription_report_async(
    subscription_id: int,
    previous_value: Optional[str] = None,
    invite_message: Optional[str] = None,
) -> None:
    """Async function for delivering subscription reports."""
    logger.info("deliver_subscription_report_async.starting", subscription_id=subscription_id)

    # Fetch subscription asynchronously
    logger.info("deliver_subscription_report_async.loading_subscription", subscription_id=subscription_id)
    subscription = await database_sync_to_async(
        Subscription.objects.select_related("created_by", "insight", "dashboard", "team").get,
        thread_sensitive=False,
    )(pk=subscription_id)

    logger.info(
        "deliver_subscription_report_async.subscription_loaded",
        subscription_id=subscription_id,
        has_dashboard=bool(subscription.dashboard_id),
        has_insight=bool(subscription.insight_id),
    )

    is_new_subscription_target = False
    if previous_value is not None:
        # If previous_value is set we are triggering a "new" or "invite" message
        is_new_subscription_target = subscription.target_value != previous_value
        logger.info(
            "deliver_subscription_report_async.checking_target_change",
            subscription_id=subscription_id,
            is_new_target=is_new_subscription_target,
        )

        if not is_new_subscription_target:
            # Same value as before so nothing to do
            logger.info("deliver_subscription_report_async.no_change_skipping", subscription_id=subscription_id)
            return

    logger.info("deliver_subscription_report_async.generating_assets", subscription_id=subscription_id)
    insights, assets = await generate_assets_async(subscription)
    logger.info(
        "deliver_subscription_report_async.assets_generated", subscription_id=subscription_id, asset_count=len(assets)
    )

    if not assets:
        logger.warning("deliver_subscription_report_async.no_assets", subscription_id=subscription_id)
        capture_exception(Exception("No assets are in this subscription"), {"subscription_id": subscription.id})
        return

    if subscription.target_type == "email":
        logger.info("deliver_subscription_report_async.sending_email", subscription_id=subscription_id)
        SUBSCRIPTION_QUEUED.labels(destination="email", execution_path="temporal").inc()

        # Send emails
        emails = subscription.target_value.split(",")
        if is_new_subscription_target:
            previous_emails = previous_value.split(",") if previous_value else []
            emails = list(set(emails) - set(previous_emails))

        logger.info(
            "deliver_subscription_report_async.email_list", subscription_id=subscription_id, email_count=len(emails)
        )

        for email in emails:
            try:
                logger.info(
                    "deliver_subscription_report_async.sending_to_email", subscription_id=subscription_id, email=email
                )
                await database_sync_to_async(send_email_subscription_report, thread_sensitive=False)(
                    email,
                    subscription,
                    assets,
                    invite_message=invite_message or "" if is_new_subscription_target else None,
                    total_asset_count=len(insights),
                    send_async=False,
                )
                logger.info(
                    "deliver_subscription_report_async.email_sent", subscription_id=subscription_id, email=email
                )
                SUBSCRIPTION_SUCCESS.labels(destination="email", execution_path="temporal").inc()
            except Exception as e:
                SUBSCRIPTION_FAILURE.labels(destination="email", execution_path="temporal").inc()
                logger.error(
                    "deliver_subscription_report_async.email_failed",
                    subscription_id=subscription.id,
                    email=email,
                    next_delivery_date=subscription.next_delivery_date,
                    destination=subscription.target_type,
                    exc_info=True,
                )
                capture_exception(e)

    elif subscription.target_type == "slack":
        logger.info("deliver_subscription_report_async.sending_slack", subscription_id=subscription_id)
        SUBSCRIPTION_QUEUED.labels(destination="slack", execution_path="temporal").inc()

        try:
            logger.info("deliver_subscription_report_async.loading_slack_integration", subscription_id=subscription_id)
            integration = await database_sync_to_async(get_slack_integration_for_team, thread_sensitive=False)(
                subscription.team_id
            )

            if not integration:
                logger.error("deliver_subscription_report_async.no_slack_integration", subscription_id=subscription_id)
                SUBSCRIPTION_FAILURE.labels(destination="slack", execution_path="temporal").inc()
                return

            logger.info("deliver_subscription_report_async.sending_slack_message", subscription_id=subscription_id)
            await send_slack_message_with_integration_async(
                integration,
                subscription,
                assets,
                total_asset_count=len(insights),
                is_new_subscription=is_new_subscription_target,
            )
            logger.info("deliver_subscription_report_async.slack_sent", subscription_id=subscription_id)
            SUBSCRIPTION_SUCCESS.labels(destination="slack", execution_path="temporal").inc()
        except Exception as e:
            SUBSCRIPTION_FAILURE.labels(destination="slack", execution_path="temporal").inc()
            logger.error(
                "deliver_subscription_report_async.slack_failed",
                subscription_id=subscription.id,
                next_delivery_date=subscription.next_delivery_date,
                destination=subscription.target_type,
                exc_info=True,
            )
            capture_exception(e)
    else:
        logger.error(
            "deliver_subscription_report_async.unsupported_target",
            subscription_id=subscription_id,
            target_type=subscription.target_type,
        )
        raise NotImplementedError(f"{subscription.target_type} is not supported")

    if not is_new_subscription_target:
        logger.info("deliver_subscription_report_async.updating_next_delivery", subscription_id=subscription_id)
        subscription.set_next_delivery_date(subscription.next_delivery_date)
        await database_sync_to_async(subscription.save, thread_sensitive=False)(update_fields=["next_delivery_date"])

    logger.info("deliver_subscription_report_async.completed", subscription_id=subscription_id)


def deliver_subscription_report_sync(
    subscription_id: int,
    previous_value: Optional[str] = None,
    invite_message: Optional[str] = None,
) -> None:
    """Sync function for delivering subscription reports."""
    subscription = Subscription.objects.select_related("created_by", "insight", "dashboard").get(pk=subscription_id)

    is_new_subscription_target = False
    if previous_value is not None:
        # If previous_value is set we are triggering a "new" or "invite" message
        is_new_subscription_target = subscription.target_value != previous_value

        if not is_new_subscription_target:
            # Same value as before so nothing to do
            return

    insights, assets = generate_assets(subscription)

    if not assets:
        capture_exception(Exception("No assets are in this subscription"), {"subscription_id": subscription.id})
        return

    if subscription.target_type == "email":
        SUBSCRIPTION_QUEUED.labels(destination="email", execution_path="celery").inc()

        # Send emails
        emails = subscription.target_value.split(",")
        if is_new_subscription_target:
            previous_emails = previous_value.split(",") if previous_value else []
            emails = list(set(emails) - set(previous_emails))

        for email in emails:
            try:
                send_email_subscription_report(
                    email,
                    subscription,
                    assets,
                    invite_message=invite_message or "" if is_new_subscription_target else None,
                    total_asset_count=len(insights),
                )
                SUBSCRIPTION_SUCCESS.labels(destination="email", execution_path="celery").inc()
            except Exception as e:
                SUBSCRIPTION_FAILURE.labels(destination="email", execution_path="celery").inc()
                logger.error(
                    "sending subscription failed",
                    subscription_id=subscription.id,
                    next_delivery_date=subscription.next_delivery_date,
                    destination=subscription.target_type,
                    exc_info=True,
                )
                capture_exception(e)

    elif subscription.target_type == "slack":
        SUBSCRIPTION_QUEUED.labels(destination="slack", execution_path="celery").inc()

        try:
            send_slack_subscription_report(
                subscription,
                assets,
                total_asset_count=len(insights),
                is_new_subscription=is_new_subscription_target,
            )
            SUBSCRIPTION_SUCCESS.labels(destination="slack", execution_path="celery").inc()
        except Exception as e:
            SUBSCRIPTION_FAILURE.labels(destination="slack", execution_path="celery").inc()
            logger.error(
                "sending subscription failed",
                subscription_id=subscription.id,
                next_delivery_date=subscription.next_delivery_date,
                destination=subscription.target_type,
                exc_info=True,
            )
            capture_exception(e)
    else:
        raise NotImplementedError(f"{subscription.target_type} is not supported")

    if not is_new_subscription_target:
        subscription.set_next_delivery_date(subscription.next_delivery_date)
        subscription.save(update_fields=["next_delivery_date"])


@shared_task(queue=CeleryQueue.SUBSCRIPTION_DELIVERY.value)
def schedule_all_subscriptions() -> None:
    """
    Schedule all past notifications (with a buffer) to be delivered
    NOTE: This task is scheduled hourly just before the hour allowing for the 15 minute timedelta to cover
    all upcoming hourly scheduled subscriptions
    """
    now_with_buffer = datetime.utcnow() + timedelta(minutes=15)
    subscriptions = (
        Subscription.objects.filter(next_delivery_date__lte=now_with_buffer, deleted=False)
        .exclude(dashboard__deleted=True)
        .exclude(insight__deleted=True)
        .select_related("team")
        .order_by("team_id")
        .all()
    )

    for team, group_subscriptions in groupby(subscriptions, key=lambda x: x.team):
        if not team_use_temporal_flag(team):
            for subscription in group_subscriptions:
                logger.info(
                    "Scheduling subscription",
                    subscription_id=subscription.id,
                    next_delivery_date=subscription.next_delivery_date,
                    destination=subscription.target_type,
                )
                deliver_subscription_report.delay(subscription.id)


report_timeout_seconds = settings.PARALLEL_ASSET_GENERATION_MAX_TIMEOUT_MINUTES * 60 * 1.5


@shared_task(
    soft_time_limit=report_timeout_seconds,
    time_limit=report_timeout_seconds + 10,
    queue=CeleryQueue.SUBSCRIPTION_DELIVERY.value,
)
def deliver_subscription_report(subscription_id: int) -> None:
    return deliver_subscription_report_sync(subscription_id)


@shared_task(
    soft_time_limit=report_timeout_seconds,
    time_limit=report_timeout_seconds + 10,
    queue=CeleryQueue.SUBSCRIPTION_DELIVERY.value,
)
def handle_subscription_value_change(
    subscription_id: int, previous_value: str, invite_message: Optional[str] = None
) -> None:
    return deliver_subscription_report_sync(subscription_id, previous_value, invite_message)


def team_use_temporal_flag(team: Team) -> bool:
    return posthoganalytics.feature_enabled(
        "use-temporal-subscriptions",
        str(team.uuid),
        groups={
            "organization": str(team.organization_id),
            "project": str(team.id),
        },
        group_properties={
            "organization": {
                "id": str(team.organization_id),
            },
            "project": {
                "id": str(team.id),
            },
        },
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    )
