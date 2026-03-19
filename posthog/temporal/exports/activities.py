import time

import structlog
import temporalio.activity
from temporalio.exceptions import ApplicationError

from posthog.event_usage import EventSource
from posthog.models.exported_asset import ExportedAsset
from posthog.slo.events import emit_slo_completed
from posthog.slo.types import SloArea, SloCompletedProperties, SloOperation, SloOutcome
from posthog.sync import database_sync_to_async
from posthog.tasks import exporter
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.exports.types import EmitDeliveryOutcomeInput, ExportAssetActivityInputs, ExportAssetResult

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def export_asset_activity(inputs: ExportAssetActivityInputs) -> ExportAssetResult:
    async with Heartbeater():
        asset = await database_sync_to_async(
            lambda: ExportedAsset.objects_including_ttl_deleted.select_related(
                "created_by", "team", "team__organization"
            ).get(pk=inputs.exported_asset_id),
            thread_sensitive=False,
        )()

        logger.info(
            "export_asset_activity.starting",
            exported_asset_id=asset.id,
            team_id=asset.team_id,
        )

        start = time.monotonic()
        try:
            await database_sync_to_async(exporter.export_asset_direct, thread_sensitive=False)(
                asset,
                limit=inputs.limit,
                max_height_pixels=inputs.max_height_pixels,
                source=EventSource(inputs.source) if inputs.source else None,
            )
        except Exception as e:
            duration_ms = (time.monotonic() - start) * 1000
            await database_sync_to_async(asset.refresh_from_db, thread_sensitive=False)()
            logger.warning(
                "export_asset_activity.failed",
                exported_asset_id=asset.id,
                team_id=asset.team_id,
                insight_id=asset.insight_id,
                failure_type=asset.failure_type,
                error=str(e),
            )
            # Wrap in ApplicationError to propagate failure metadata as details
            # while preserving the exception class name for retry policy matching.
            # Detail order: [failure_type, duration_ms, export_format, attempt]
            raise ApplicationError(
                str(e),
                asset.failure_type,
                duration_ms,
                asset.export_format,
                temporalio.activity.info().attempt,
                type=type(e).__name__,
            ) from e

        duration_ms = (time.monotonic() - start) * 1000
        await database_sync_to_async(asset.refresh_from_db, thread_sensitive=False)()

        return ExportAssetResult(
            exported_asset_id=asset.id,
            success=asset.has_content,
            failure_type=asset.failure_type,
            insight_id=asset.insight_id,
            duration_ms=duration_ms,
            export_format=asset.export_format,
            attempts=temporalio.activity.info().attempt,
        )


@temporalio.activity.defn
async def emit_delivery_outcome(inputs: EmitDeliveryOutcomeInput) -> None:
    emit_slo_completed(
        distinct_id=inputs.distinct_id,
        properties=SloCompletedProperties(
            operation=SloOperation.SUBSCRIPTION_DELIVERY,
            resource_id=str(inputs.subscription_id),
            area=SloArea.ANALYTIC_PLATFORM,
            team_id=inputs.team_id,
            outcome=SloOutcome(inputs.outcome),
            duration_ms=inputs.duration_ms,
        ),
        extra_properties={
            "subscription_id": inputs.subscription_id,
            "assets_with_content": inputs.assets_with_content,
            "total_assets": inputs.total_assets,
            "failure_types": inputs.failure_types,
        },
    )
    logger.info(
        "emit_delivery_outcome.emitted",
        subscription_id=inputs.subscription_id,
        outcome=inputs.outcome,
    )
