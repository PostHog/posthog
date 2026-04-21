import traceback

import structlog
import temporalio.activity
from temporalio.exceptions import ApplicationError

from posthog.event_usage import EventSource
from posthog.models.exported_asset import ExportedAsset
from posthog.sync import database_sync_to_async
from posthog.tasks import exporter
from posthog.tasks.exports.failure_handler import SYSTEM_ERROR_NAMES
from posthog.temporal.common.errors import MAX_ERROR_MESSAGE_CHARS, MAX_ERROR_TRACE_CHARS, truncate_for_temporal_payload
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.exports.types import ExportAssetActivityInputs, ExportAssetResult

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

        try:
            await database_sync_to_async(exporter.export_asset_direct, thread_sensitive=False)(
                asset,
                source=EventSource(inputs.source) if inputs.source else None,
            )
        except Exception as e:
            await database_sync_to_async(asset.refresh_from_db, thread_sensitive=False)()
            exception_class = type(e).__name__
            error_trace = "\n".join(traceback.format_exception(e)[:5])
            logger.warning(
                "export_asset_activity.failed",
                exported_asset_id=asset.id,
                team_id=asset.team_id,
                insight_id=asset.insight_id,
                exception_class=exception_class,
                error=str(e),
            )
            # Wrap in ApplicationError to propagate failure metadata as details while
            # preserving the exception class for retry-policy matching (transient CH/network
            # errors retry; programming errors and Chrome crashes fail fast). See
            # posthog.temporal.exports.types.extract_error_details. Strings are truncated so
            # an upstream exception can't blow out the 2 MiB payload envelope.
            raise ApplicationError(
                truncate_for_temporal_payload(str(e), MAX_ERROR_MESSAGE_CHARS),
                truncate_for_temporal_payload(error_trace, MAX_ERROR_TRACE_CHARS),
                type=exception_class,
                non_retryable=exception_class not in SYSTEM_ERROR_NAMES,
            ) from e

        await database_sync_to_async(asset.refresh_from_db, thread_sensitive=False)()

        return ExportAssetResult(
            exported_asset_id=asset.id,
            success=asset.has_content,
        )
