import uuid
import typing
import datetime as dt
from datetime import datetime

from django.utils import timezone as tz

import temporalio.activity
from slack_sdk.errors import SlackApiError
from structlog import get_logger
from temporalio.exceptions import ApplicationError

from posthog.exceptions_capture import capture_exception
from posthog.models.exported_asset import ExportedAsset
from posthog.models.insight import Insight
from posthog.models.subscription import Subscription, SubscriptionDelivery
from posthog.sync import database_sync_to_async
from posthog.temporal.subscriptions.insight_snapshot import (
    build_initial_content_snapshot,
    build_insight_delivery_snapshot,
)
from posthog.temporal.subscriptions.types import (
    CreateDeliveryRecordInputs,
    CreateExportAssetsInputs,
    CreateExportAssetsResult,
    DeliverSubscriptionInputs,
    DeliverSubscriptionResult,
    FetchDueSubscriptionsActivityInputs,
    RecipientResult,
    SubscriptionInfo,
    UpdateDeliveryRecordInputs,
)

from products.dashboards.backend.models.dashboard_tile import DashboardTile

from ee.tasks.subscriptions import SLACK_USER_CONFIG_ERRORS, SUPPORTED_TARGET_TYPES, _capture_delivery_failed_event
from ee.tasks.subscriptions.email_subscriptions import send_email_subscription_report
from ee.tasks.subscriptions.slack_subscriptions import (
    get_slack_integration_for_team,
    send_slack_message_with_integration_async,
)

LOGGER = get_logger(__name__)


@temporalio.activity.defn
async def fetch_due_subscriptions_activity(inputs: FetchDueSubscriptionsActivityInputs) -> list[SubscriptionInfo]:
    now_with_buffer = dt.datetime.utcnow() + dt.timedelta(minutes=inputs.buffer_minutes)
    await LOGGER.ainfo("Fetching due subscriptions", deadline=now_with_buffer)

    @database_sync_to_async(thread_sensitive=False)
    def get_subscriptions() -> list[SubscriptionInfo]:
        return [
            SubscriptionInfo(
                subscription_id=sub["id"],
                team_id=sub["team_id"],
                distinct_id=str(sub["created_by__distinct_id"])
                if sub["created_by__distinct_id"]
                else str(sub["team_id"]),
                next_delivery_date=sub["next_delivery_date"].isoformat() if sub["next_delivery_date"] else None,
            )
            for sub in Subscription.objects.filter(next_delivery_date__lte=now_with_buffer, deleted=False)
            .exclude(dashboard__deleted=True)
            .exclude(insight__deleted=True)
            .values("id", "team_id", "created_by__distinct_id", "next_delivery_date")
        ]

    subscriptions = await get_subscriptions()
    await LOGGER.ainfo("Fetched due subscriptions", count=len(subscriptions))

    return subscriptions


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
        tile_insight_pairs: list[tuple[DashboardTile | None, Insight]] = [
            (tile, tile.insight) for tile in tiles if tile.insight
        ]

        selected_ids = await database_sync_to_async(
            lambda: (
                set(subscription.dashboard_export_insights.values_list("id", flat=True))
                if subscription.dashboard_export_insights.exists()
                else None
            ),
            thread_sensitive=False,
        )()
        if selected_ids:
            tile_insight_pairs = [(t, i) for t, i in tile_insight_pairs if i.id in selected_ids]
    elif subscription.insight:
        tile_insight_pairs = [(None, subscription.insight)]
    else:
        raise Exception("There are no insights to be sent for this Subscription")

    total_insight_count = len(tile_insight_pairs)
    export_pairs = tile_insight_pairs[: inputs.max_asset_count]

    expiry = ExportedAsset.compute_expires_after(ExportedAsset.ExportFormat.PNG)
    assets = [
        ExportedAsset(
            team=team,
            export_format=ExportedAsset.ExportFormat.PNG,
            insight=insight,
            dashboard=dashboard,
            expires_after=expiry,
        )
        for _tile, insight in export_pairs
    ]
    await database_sync_to_async(ExportedAsset.objects.bulk_create, thread_sensitive=False)(assets)

    @database_sync_to_async(thread_sensitive=False)
    def build_insight_snapshots() -> list[dict[str, typing.Any]]:
        return [
            build_insight_delivery_snapshot(
                insight=insight,
                team=team,
                dashboard=dashboard,
                tile=tile,
                user=subscription.created_by,
            )
            for tile, insight in export_pairs
        ]

    insight_snapshots = await build_insight_snapshots()

    await LOGGER.ainfo(
        "create_export_assets.assets_created",
        subscription_id=inputs.subscription_id,
        asset_count=len(assets),
        total_insights=total_insight_count,
    )
    return CreateExportAssetsResult(
        exported_asset_ids=[a.id for a in assets],
        total_insight_count=total_insight_count,
        team_id=team.id,
        distinct_id=str(subscription.created_by.distinct_id) if subscription.created_by else str(team.id),
        target_type=subscription.target_type,
        insight_snapshots=insight_snapshots,
    )


@temporalio.activity.defn
async def deliver_subscription(inputs: DeliverSubscriptionInputs) -> DeliverSubscriptionResult:
    recipient_results: list[RecipientResult] = []

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
        return DeliverSubscriptionResult(recipient_results=recipient_results)

    assets_by_id = await database_sync_to_async(
        lambda: {
            a.id: a
            for a in ExportedAsset.objects_including_ttl_deleted.select_related("insight", "dashboard").filter(
                pk__in=inputs.exported_asset_ids
            )
        },
        thread_sensitive=False,
    )()
    # Preserve the order from create_export_assets (sorted by dashboard tile layout)
    assets = [assets_by_id[aid] for aid in inputs.exported_asset_ids if aid in assets_by_id]

    if not assets:
        LOGGER.warning("deliver_subscription.no_assets", subscription_id=inputs.subscription_id)
        capture_exception(Exception("No assets are in this subscription"), {"subscription_id": inputs.subscription_id})
        return DeliverSubscriptionResult(recipient_results=recipient_results)

    if subscription.target_type == "email":
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
                success_count += 1
                recipient_results.append(RecipientResult(recipient=email, status="success"))
            except Exception as e:
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
                recipient_results.append(
                    RecipientResult(
                        recipient=email,
                        status="failed",
                        error={"message": str(e), "type": type(e).__name__},
                    )
                )

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
                missing_integration_error = {
                    "message": "No Slack integration configured",
                    "type": "missing_integration",
                }
                recipient_results.append(
                    RecipientResult(
                        recipient=subscription.target_value,
                        status="failed",
                        error=missing_integration_error,
                    )
                )
                # Same shape as ProcessSubscriptionWorkflow success-path serialization so
                # update_delivery_record gets per-recipient rows from ActivityError.details.
                raise ApplicationError(
                    "No Slack integration configured for this team",
                    {
                        "recipient_results": [
                            {
                                "recipient": r.recipient,
                                "status": r.status,
                                **({"error": r.error} if r.error else {}),
                            }
                            for r in recipient_results
                        ]
                    },
                    non_retryable=True,
                )

            LOGGER.info("deliver_subscription.sending_slack_message", subscription_id=subscription.id)
            delivery_result = await send_slack_message_with_integration_async(
                integration,
                subscription,
                assets,
                total_asset_count=inputs.total_insight_count,
                is_new_subscription=inputs.is_new_subscription_target,
            )

            if delivery_result.is_complete_success:
                await LOGGER.ainfo(
                    "deliver_subscription.slack_sent",
                    subscription_id=inputs.subscription_id,
                )
                recipient_results.append(RecipientResult(recipient=subscription.target_value, status="success"))
            elif delivery_result.is_partial_failure:
                await LOGGER.awarning(
                    "deliver_subscription.slack_partial_failure",
                    subscription_id=inputs.subscription_id,
                    failed_thread_count=len(delivery_result.failed_thread_message_indices),
                    total_thread_count=delivery_result.total_thread_messages,
                )
                recipient_results.append(
                    RecipientResult(
                        recipient=subscription.target_value,
                        status="partial",
                        error={
                            "message": f"{len(delivery_result.failed_thread_message_indices)} thread message(s) failed",
                            "type": "partial_thread_failure",
                        },
                    )
                )

        except ApplicationError:
            raise
        except Exception as e:
            is_user_config_error = isinstance(e, SlackApiError) and e.response.get("error") in SLACK_USER_CONFIG_ERRORS
            _capture_delivery_failed_event(subscription, e)
            LOGGER.error(
                "deliver_subscription.slack_failed",
                subscription_id=subscription.id,
                next_delivery_date=subscription.next_delivery_date,
                destination=subscription.target_type,
                exc_info=True,
            )
            capture_exception(e)
            recipient_results.append(
                RecipientResult(
                    recipient=subscription.target_value,
                    status="failed",
                    error={"message": str(e), "type": type(e).__name__},
                )
            )
            if not is_user_config_error:
                raise  # Transient Slack errors — let Temporal retry

    await LOGGER.ainfo(
        "deliver_subscription.completed",
        subscription_id=inputs.subscription_id,
        target_type=subscription.target_type,
    )
    return DeliverSubscriptionResult(recipient_results=recipient_results)


@temporalio.activity.defn
async def create_delivery_record(inputs: CreateDeliveryRecordInputs) -> uuid.UUID:
    scheduled_at = datetime.fromisoformat(inputs.scheduled_at) if inputs.scheduled_at else None

    @database_sync_to_async(thread_sensitive=False)
    def _create() -> uuid.UUID:
        subscription = Subscription.objects.select_related("insight", "dashboard").get(pk=inputs.subscription_id)
        if subscription.team_id != inputs.team_id:
            raise ValueError(
                f"Subscription team_id ({subscription.team_id}) does not match inputs.team_id ({inputs.team_id})"
            )

        content_snapshot = build_initial_content_snapshot(subscription)

        delivery, _created = SubscriptionDelivery.objects.get_or_create(
            idempotency_key=inputs.idempotency_key,
            defaults={
                "subscription": subscription,
                "team_id": inputs.team_id,
                "temporal_workflow_id": inputs.temporal_workflow_id,
                "trigger_type": inputs.trigger_type,
                "scheduled_at": scheduled_at,
                "target_type": subscription.target_type,
                "target_value": subscription.target_value,
                "content_snapshot": content_snapshot,
                "status": SubscriptionDelivery.Status.STARTING,
            },
        )
        return delivery.id

    delivery_id = await _create()
    await LOGGER.ainfo(
        "create_delivery_record.created",
        subscription_id=inputs.subscription_id,
        delivery_id=delivery_id,
    )
    return delivery_id


@temporalio.activity.defn
async def update_delivery_record(inputs: UpdateDeliveryRecordInputs) -> None:
    @database_sync_to_async(thread_sensitive=False)
    def _update() -> None:
        delivery = SubscriptionDelivery.objects.get(pk=inputs.delivery_id)
        update_fields: list[str] = ["status", "last_updated_at"]
        delivery.status = inputs.status

        if inputs.exported_asset_ids is not None:
            delivery.exported_asset_ids = inputs.exported_asset_ids
            update_fields.append("exported_asset_ids")
        if inputs.content_snapshot is not None:
            # Merge so workflow patches (e.g. total_insight_count) do not wipe create_delivery_record snapshot.
            delivery.content_snapshot = {**(delivery.content_snapshot or {}), **inputs.content_snapshot}
            update_fields.append("content_snapshot")
        if inputs.recipient_results is not None:
            delivery.recipient_results = inputs.recipient_results
            update_fields.append("recipient_results")
        delivery.error = inputs.error
        update_fields.append("error")
        if inputs.finished:
            delivery.finished_at = tz.now()
            update_fields.append("finished_at")

        delivery.save(update_fields=update_fields)

    await _update()
    await LOGGER.ainfo(
        "update_delivery_record.updated",
        delivery_id=inputs.delivery_id,
        status=inputs.status,
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
