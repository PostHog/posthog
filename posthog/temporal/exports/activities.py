import traceback

import structlog
import temporalio.activity
from temporalio.exceptions import ApplicationError

from posthog.event_usage import EventSource
from posthog.sync import database_sync_to_async
from posthog.tasks import exporter
from posthog.temporal.common.errors import MAX_ERROR_MESSAGE_CHARS, MAX_ERROR_TRACE_CHARS, truncate_for_temporal_payload
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.exports.types import ExportAssetActivityInputs, ExportAssetResult

from products.exports.backend.models.exported_asset import ExportedAsset
from products.exports.backend.tasks.failure_handler import SYSTEM_ERROR_NAMES, TIMEOUT_ERROR_NAMES, ExportCancelled

logger = structlog.get_logger(__name__)

# Render/query timeouts are transient and must stay retryable; an explicit
# cancellation is terminal even though it lives in TIMEOUT_ERROR_NAMES.
RETRYABLE_ERROR_NAMES = SYSTEM_ERROR_NAMES | (TIMEOUT_ERROR_NAMES - {ExportCancelled.__name__})


@temporalio.activity.defn
async def export_asset_activity(inputs: ExportAssetActivityInputs) -> ExportAssetResult:
    async with Heartbeater():
        try:
            asset = await database_sync_to_async(
                lambda: ExportedAsset.objects_including_ttl_deleted.select_related(
                    "created_by", "team", "team__organization"
                ).get(pk=inputs.exported_asset_id),
                thread_sensitive=False,
            )()
        except ExportedAsset.DoesNotExist as e:
            # A hard-deleted asset can never come back, so retrying only burns the retry budget and
            # ends the workflow on DoesNotExist instead of the real cause. Fail fast.
            raise ApplicationError(
                f"Exported asset {inputs.exported_asset_id} no longer exists",
                type=type(e).__name__,
                non_retryable=True,
            ) from e

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
            # The row can be deleted mid-render, so a refresh here would raise DoesNotExist and hide
            # the real failure before it reaches the ApplicationError wrapper below.
            row_missing = False
            try:
                await database_sync_to_async(asset.refresh_from_db, thread_sensitive=False)()
            except ExportedAsset.DoesNotExist:
                row_missing = True
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
            # errors retry; programming errors and Chrome crashes fail fast). A missing row is
            # terminal regardless of the render error: the asset is gone, so no retry can succeed.
            # See posthog.temporal.exports.types.extract_error_details. Strings are truncated so
            # an upstream exception can't blow out the 2 MiB payload envelope.
            raise ApplicationError(
                truncate_for_temporal_payload(str(e), MAX_ERROR_MESSAGE_CHARS),
                truncate_for_temporal_payload(error_trace, MAX_ERROR_TRACE_CHARS),
                type=exception_class,
                non_retryable=row_missing or exception_class not in RETRYABLE_ERROR_NAMES,
            ) from e

        await database_sync_to_async(asset.refresh_from_db, thread_sensitive=False)()

        return ExportAssetResult(
            exported_asset_id=asset.id,
            success=asset.has_content,
        )
