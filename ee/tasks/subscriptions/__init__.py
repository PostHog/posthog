from typing import Optional

import structlog
import posthoganalytics
from slack_sdk.errors import SlackApiError
from temporalio import activity, workflow
from temporalio.common import MetricCounter, MetricMeter

from posthog.exceptions_capture import capture_exception
from posthog.models.subscription import Subscription
from posthog.sync import database_sync_to_async
from posthog.tasks.exports.failure_handler import is_user_query_error_type

from ee.tasks.subscriptions.email_subscriptions import send_email_subscription_report
from ee.tasks.subscriptions.slack_subscriptions import (
    get_slack_integration_for_team,
    send_slack_message_with_integration_async,
)
from ee.tasks.subscriptions.subscription_utils import _has_asset_failed, generate_assets_async

logger = structlog.get_logger(__name__)

# Slack errors that are user configuration issues, not system failures
SLACK_USER_CONFIG_ERRORS = frozenset(
    ["not_in_channel", "account_inactive", "is_archived", "channel_not_found", "invalid_auth"]
)


# Temporal metrics for temporal workers
def get_metric_meter() -> MetricMeter:
    """Get metric meter for the current context (activity or workflow)."""
    if activity.in_activity():
        return activity.metric_meter()
    elif workflow.in_workflow():
        return workflow.metric_meter()
    else:
        raise RuntimeError("Not within workflow or activity context")


def get_subscription_queued_metric(destination: str, execution_path: str) -> MetricCounter:
    return (
        get_metric_meter()
        .with_additional_attributes({"destination": destination, "execution_path": execution_path})
        .create_counter(
            "subscription_queued",
            "A subscription was queued for delivery",
        )
    )


def get_subscription_success_metric(destination: str, execution_path: str) -> MetricCounter:
    return (
        get_metric_meter()
        .with_additional_attributes({"destination": destination, "execution_path": execution_path})
        .create_counter(
            "subscription_send_success",
            "A subscription was sent successfully",
        )
    )


def get_subscription_failure_metric(
    destination: str, execution_path: str, failure_type: str = "complete"
) -> MetricCounter:
    return (
        get_metric_meter()
        .with_additional_attributes(
            {"destination": destination, "execution_path": execution_path, "failure_type": failure_type}
        )
        .create_counter(
            "subscription_send_failure",
            "A subscription failed to send",
        )
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

    # Only count system failures in metrics, not user config errors
    failed_assets = [a for a in assets if _has_asset_failed(a)]
    system_failures = [a for a in failed_assets if not is_user_query_error_type(a.exception_type)]
    if system_failures:
        get_subscription_failure_metric(subscription.target_type, "temporal", failure_type="asset_generation").add(1)
        logger.warn(
            "deliver_subscription_report_async.failed_asset_generation",
            subscription_id=subscription_id,
            asset_count=len(assets),
            assets=[
                {
                    "exported_asset_id": a.id,
                    "exception_type": a.exception_type,
                    "content_location": a.content_location,
                }
                for a in assets
            ],
        )

    if not assets:
        logger.warning("deliver_subscription_report_async.no_assets", subscription_id=subscription_id)
        capture_exception(Exception("No assets are in this subscription"), {"subscription_id": subscription.id})
        return

    if subscription.target_type == "email":
        logger.info("deliver_subscription_report_async.sending_email", subscription_id=subscription_id)
        get_subscription_queued_metric("email", "temporal").add(1)

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
                get_subscription_success_metric("email", "temporal").add(1)
            except Exception as e:
                get_subscription_failure_metric("email", "temporal").add(1)
                _capture_delivery_failed_event(subscription, e)
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
        get_subscription_queued_metric("slack", "temporal").add(1)

        try:
            logger.info("deliver_subscription_report_async.loading_slack_integration", subscription_id=subscription_id)
            integration = await database_sync_to_async(get_slack_integration_for_team, thread_sensitive=False)(
                subscription.team_id
            )

            if not integration:
                logger.warn("deliver_subscription_report_async.no_slack_integration", subscription_id=subscription_id)
                return

            logger.info("deliver_subscription_report_async.sending_slack_message", subscription_id=subscription_id)
            delivery_result = await send_slack_message_with_integration_async(
                integration,
                subscription,
                assets,
                total_asset_count=len(insights),
                is_new_subscription=is_new_subscription_target,
            )

            if delivery_result.is_complete_success:
                logger.info("deliver_subscription_report_async.slack_sent", subscription_id=subscription_id)
                get_subscription_success_metric("slack", "temporal").add(1)
            elif delivery_result.is_partial_failure:
                logger.warning(
                    "deliver_subscription_report_async.slack_partial_failure",
                    subscription_id=subscription_id,
                    failed_thread_count=len(delivery_result.failed_thread_message_indices),
                    total_thread_count=delivery_result.total_thread_messages,
                )
                get_subscription_failure_metric("slack", "temporal", failure_type="partial").add(1)

        except Exception as e:
            is_user_config_error = isinstance(e, SlackApiError) and e.response.get("error") in SLACK_USER_CONFIG_ERRORS

            if not is_user_config_error:
                get_subscription_failure_metric("slack", "temporal", failure_type="complete").add(1)

            _capture_delivery_failed_event(subscription, e)
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


def _capture_delivery_failed_event(subscription: Subscription, e: Exception) -> None:
    posthoganalytics.capture(
        distinct_id=str(subscription.created_by_id),
        event="subscription_delivery_failed",
        properties={
            "subscription_id": subscription.id,
            "team_id": subscription.team_id,
            "target_type": subscription.target_type,
            "exception": str(e),
            "exception_type": type(e).__name__,
        },
    )
