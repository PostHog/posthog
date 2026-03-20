import datetime as dt

import temporalio.activity
from slack_sdk.errors import SlackApiError
from structlog import get_logger

from posthog.exceptions_capture import capture_exception
from posthog.models.exported_asset import ExportedAsset
from posthog.models.subscription import Subscription
from posthog.sync import database_sync_to_async
from posthog.temporal.subscriptions.types import (
    CreateExportAssetsInputs,
    CreateExportAssetsResult,
    DeliverSubscriptionInputs,
    FetchDueSubscriptionsActivityInputs,
)

from ee.tasks.subscriptions import (
    SLACK_USER_CONFIG_ERRORS,
    SUPPORTED_TARGET_TYPES,
    _capture_delivery_failed_event,
    get_subscription_failure_metric,
    get_subscription_queued_metric,
    get_subscription_success_metric,
)
from ee.tasks.subscriptions.email_subscriptions import send_email_subscription_report
from ee.tasks.subscriptions.slack_subscriptions import (
    get_slack_integration_for_team,
    send_slack_message_with_integration_async,
)

LOGGER = get_logger(__name__)


@temporalio.activity.defn
async def fetch_due_subscriptions_activity(inputs: FetchDueSubscriptionsActivityInputs) -> list[int]:
    now_with_buffer = dt.datetime.utcnow() + dt.timedelta(minutes=inputs.buffer_minutes)
    await LOGGER.ainfo("Fetching due subscriptions", deadline=now_with_buffer)

    @database_sync_to_async(thread_sensitive=False)
    def get_subscription_ids() -> list[int]:
        return list(
            Subscription.objects.filter(next_delivery_date__lte=now_with_buffer, deleted=False)
            .exclude(dashboard__deleted=True)
            .exclude(insight__deleted=True)
            .values_list("id", flat=True)
        )

    subscription_ids = await get_subscription_ids()
    await LOGGER.ainfo("Fetched due subscriptions", count=len(subscription_ids))

    return subscription_ids


@temporalio.activity.defn
async def create_export_assets(inputs: CreateExportAssetsInputs) -> CreateExportAssetsResult:
    await LOGGER.ainfo(
        "create_export_assets.starting",
        subscription_id=inputs.subscription_id,
    )

    subscription = await database_sync_to_async(
        Subscription.objects.select_related("created_by", "insight", "dashboard", "team").get,
        thread_sensitive=False,
    )(pk=inputs.subscription_id)

    team = subscription.team
    dashboard = subscription.dashboard

    await LOGGER.ainfo(
        "create_export_assets.loaded",
        subscription_id=inputs.subscription_id,
        has_dashboard=bool(dashboard),
        has_insight=bool(subscription.insight_id),
        target_type=subscription.target_type,
    )

    # Early exit if target value hasn't changed — avoids creating orphaned assets
    if inputs.previous_value is not None and subscription.target_value == inputs.previous_value:
        await LOGGER.ainfo(
            "create_export_assets.no_change_skipping",
            subscription_id=inputs.subscription_id,
        )
        return CreateExportAssetsResult(
            exported_asset_ids=[],
            total_insight_count=0,
            team_id=team.id,
        )

    if dashboard:
        tiles = await database_sync_to_async(
            lambda: list(
                dashboard.tiles.select_related("insight").filter(insight__isnull=False, insight__deleted=False).all()
            ),
            thread_sensitive=False,
        )()
        tiles.sort(
            key=lambda x: (
                (x.layouts or {}).get("sm", {}).get("y", 100),
                (x.layouts or {}).get("sm", {}).get("x", 100),
            )
        )
        insights = [tile.insight for tile in tiles if tile.insight]

        selected_ids = await database_sync_to_async(
            lambda: set(subscription.dashboard_export_insights.values_list("id", flat=True))
            if subscription.dashboard_export_insights.exists()
            else None,
            thread_sensitive=False,
        )()
        if selected_ids:
            insights = [i for i in insights if i.id in selected_ids]
    elif subscription.insight:
        insights = [subscription.insight]
    else:
        raise Exception("There are no insights to be sent for this Subscription")

    expiry = ExportedAsset.compute_expires_after(ExportedAsset.ExportFormat.PNG)
    assets = [
        ExportedAsset(
            team=team,
            export_format=ExportedAsset.ExportFormat.PNG,
            insight=insight,
            dashboard=dashboard,
            expires_after=expiry,
        )
        for insight in insights[: inputs.max_asset_count]
    ]
    await database_sync_to_async(ExportedAsset.objects.bulk_create, thread_sensitive=False)(assets)

    await LOGGER.ainfo(
        "create_export_assets.assets_created",
        subscription_id=inputs.subscription_id,
        asset_count=len(assets),
        total_insights=len(insights),
    )
    return CreateExportAssetsResult(
        exported_asset_ids=[a.id for a in assets],
        total_insight_count=len(insights),
        team_id=team.id,
        target_type=subscription.target_type,
    )


@temporalio.activity.defn
async def deliver_subscription(inputs: DeliverSubscriptionInputs) -> None:
    subscription = await database_sync_to_async(
        Subscription.objects.select_related("created_by", "insight", "dashboard", "team", "integration").get,
        thread_sensitive=False,
    )(pk=inputs.subscription_id)

    await LOGGER.ainfo(
        "deliver_subscription.starting",
        subscription_id=inputs.subscription_id,
        target_type=subscription.target_type,
        asset_count=len(inputs.exported_asset_ids),
        is_new=inputs.is_new_subscription_target,
    )

    if subscription.target_type not in SUPPORTED_TARGET_TYPES:
        LOGGER.warning(
            "deliver_subscription.unsupported_target",
            subscription_id=inputs.subscription_id,
            target_type=subscription.target_type,
        )
        return

    assets = await database_sync_to_async(
        lambda: list(
            ExportedAsset.objects_including_ttl_deleted.select_related("insight").filter(
                pk__in=inputs.exported_asset_ids
            )
        ),
        thread_sensitive=False,
    )()

    if not assets:
        LOGGER.warning("deliver_subscription.no_assets", subscription_id=inputs.subscription_id)
        capture_exception(Exception("No assets are in this subscription"), {"subscription_id": inputs.subscription_id})
        return

    if subscription.target_type == "email":
        get_subscription_queued_metric("email", "temporal").add(1)

        emails = subscription.target_value.split(",")
        await LOGGER.ainfo(
            "deliver_subscription.sending_email",
            subscription_id=inputs.subscription_id,
            recipient_count=len(emails),
        )
        if inputs.is_new_subscription_target:
            previous_emails = inputs.previous_value.split(",") if inputs.previous_value else []
            emails = list(set(emails) - set(previous_emails))

        last_error: Exception | None = None
        success_count = 0
        for email in emails:
            try:
                await database_sync_to_async(send_email_subscription_report, thread_sensitive=False)(
                    email,
                    subscription,
                    assets,
                    invite_message=inputs.invite_message or "" if inputs.is_new_subscription_target else None,
                    total_asset_count=inputs.total_insight_count,
                    send_async=False,
                )
                get_subscription_success_metric("email", "temporal").add(1)
                success_count += 1
            except Exception as e:
                get_subscription_failure_metric("email", "temporal").add(1)
                _capture_delivery_failed_event(subscription, e)
                LOGGER.error(
                    "deliver_subscription.email_failed",
                    subscription_id=subscription.id,
                    email=email,
                    next_delivery_date=subscription.next_delivery_date,
                    destination=subscription.target_type,
                    exc_info=True,
                )
                capture_exception(e)
                last_error = e

        await LOGGER.ainfo(
            "deliver_subscription.email_complete",
            subscription_id=inputs.subscription_id,
            success_count=success_count,
            total_count=len(emails),
        )

        # Only retry if ALL recipients failed — partial success is acceptable
        # to avoid duplicate sends to already-delivered recipients
        if last_error is not None and success_count == 0:
            raise last_error

    elif subscription.target_type == "slack":
        get_subscription_queued_metric("slack", "temporal").add(1)

        try:
            integration = subscription.integration
            if integration is None:
                integration = await database_sync_to_async(get_slack_integration_for_team, thread_sensitive=False)(
                    subscription.team_id
                )
            elif integration.kind != "slack":
                LOGGER.warn(
                    "deliver_subscription.invalid_integration_kind",
                    subscription_id=subscription.id,
                    integration_id=integration.id,
                    kind=integration.kind,
                )
                integration = await database_sync_to_async(get_slack_integration_for_team, thread_sensitive=False)(
                    subscription.team_id
                )

            if not integration:
                LOGGER.warning(
                    "deliver_subscription.no_slack_integration",
                    subscription_id=inputs.subscription_id,
                )
                return

            LOGGER.info("deliver_subscription.sending_slack_message", subscription_id=subscription.id)
            delivery_result = await send_slack_message_with_integration_async(
                integration,
                subscription,
                assets,
                total_asset_count=inputs.total_insight_count,
                is_new_subscription=inputs.is_new_subscription_target,
            )

            if delivery_result.is_complete_success:
                get_subscription_success_metric("slack", "temporal").add(1)
                await LOGGER.ainfo(
                    "deliver_subscription.slack_sent",
                    subscription_id=inputs.subscription_id,
                )
            elif delivery_result.is_partial_failure:
                get_subscription_failure_metric("slack", "temporal", failure_type="partial").add(1)
                await LOGGER.awarning(
                    "deliver_subscription.slack_partial_failure",
                    subscription_id=inputs.subscription_id,
                    failed_thread_count=len(delivery_result.failed_thread_message_indices),
                    total_thread_count=delivery_result.total_thread_messages,
                )

        except Exception as e:
            is_user_config_error = isinstance(e, SlackApiError) and e.response.get("error") in SLACK_USER_CONFIG_ERRORS

            if not is_user_config_error:
                get_subscription_failure_metric("slack", "temporal", failure_type="complete").add(1)

            _capture_delivery_failed_event(subscription, e)
            LOGGER.error(
                "deliver_subscription.slack_failed",
                subscription_id=subscription.id,
                next_delivery_date=subscription.next_delivery_date,
                destination=subscription.target_type,
                exc_info=True,
            )
            capture_exception(e)
            if not is_user_config_error:
                raise  # Transient Slack errors — let Temporal retry

    await LOGGER.ainfo(
        "deliver_subscription.completed",
        subscription_id=inputs.subscription_id,
        target_type=subscription.target_type,
    )


@temporalio.activity.defn
async def advance_next_delivery_date(subscription_id: int) -> None:
    subscription = await database_sync_to_async(Subscription.objects.get, thread_sensitive=False)(pk=subscription_id)
    subscription.set_next_delivery_date(subscription.next_delivery_date)
    await database_sync_to_async(subscription.save, thread_sensitive=False)(update_fields=["next_delivery_date"])
    await LOGGER.ainfo(
        "advance_next_delivery_date.updated",
        subscription_id=subscription_id,
        next_delivery_date=subscription.next_delivery_date,
    )
