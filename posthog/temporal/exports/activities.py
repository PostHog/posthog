import traceback

import structlog
import temporalio.activity
from temporalio.exceptions import ApplicationError

from posthog.event_usage import EventSource
from posthog.sync import database_sync_to_async
from posthog.tasks import exporter
from posthog.temporal.common.errors import MAX_ERROR_MESSAGE_CHARS, MAX_ERROR_TRACE_CHARS, truncate_for_temporal_payload
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.exports.types import ExportAssetActivityInputs, ExportAssetResult, RecordExportFailureInputs

from products.exports.backend.models.exported_asset import ExportedAsset
from products.exports.backend.tasks.failure_handler import (
    SYSTEM_ERROR_NAMES,
    TIMEOUT_ERROR_NAMES,
    ExportCancelled,
    classify_failure_type,
)

logger = structlog.get_logger(__name__)

# Render/query timeouts are transient and must stay retryable; an explicit
# cancellation is terminal even though it lives in TIMEOUT_ERROR_NAMES.
RETRYABLE_ERROR_NAMES = SYSTEM_ERROR_NAMES | (TIMEOUT_ERROR_NAMES - {ExportCancelled.__name__})


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
                non_retryable=exception_class not in RETRYABLE_ERROR_NAMES,
            ) from e

        await database_sync_to_async(asset.refresh_from_db, thread_sensitive=False)()

        return ExportAssetResult(
            exported_asset_id=asset.id,
            success=asset.has_content,
        )


@temporalio.activity.defn
async def record_export_failure_activity(inputs: RecordExportFailureInputs) -> None:
    """Persist a terminal export failure onto the asset as a safety net.

    ``export_asset_direct`` records failures in-process, but a worker that is hard-killed
    (OOM, activity timeout, pod eviction) never reaches that handler, leaving the asset
    empty with no exception. The download endpoint can then only surface that silent
    failure as a bare 404. Once the workflow has exhausted its retries the export is
    terminally failed, so we record that here. Idempotent: never overwrites content or a
    more specific exception already recorded in-process.
    """

    def _record() -> None:
        asset = ExportedAsset.objects_including_ttl_deleted.get(pk=inputs.exported_asset_id)
        if asset.has_content or asset.exception:
            return
        asset.exception = inputs.message
        asset.exception_type = inputs.exception_type
        asset.failure_type = classify_failure_type(inputs.exception_type)
        asset.save(update_fields=["exception", "exception_type", "failure_type"])

    await database_sync_to_async(_record, thread_sensitive=False)()
