import traceback

import structlog
import temporalio.activity
from temporalio.exceptions import ApplicationError

from posthog.event_usage import EventSource
from posthog.models.exported_asset import ExportedAsset
from posthog.sync import database_sync_to_async
from posthog.tasks import exporter
from posthog.tasks.exports.failure_handler import SYSTEM_ERROR_NAMES, USER_QUERY_ERROR_NAMES
from posthog.temporal.common.errors import MAX_ERROR_MESSAGE_CHARS, MAX_ERROR_TRACE_CHARS, truncate_for_temporal_payload
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.exports.types import ExportAssetActivityInputs, ExportAssetResult, ExportError

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
            error_message = truncate_for_temporal_payload(str(e), MAX_ERROR_MESSAGE_CHARS)
            error_trace = truncate_for_temporal_payload(
                "\n".join(traceback.format_exception(e)[:5]), MAX_ERROR_TRACE_CHARS
            )
            logger.warning(
                "export_asset_activity.failed",
                exported_asset_id=asset.id,
                team_id=asset.team_id,
                insight_id=asset.insight_id,
                exception_class=exception_class,
                error=str(e),
            )

            # User-query failures (bad HogQL, exceeded column limits, etc.) are
            # bugs in the user's saved query, not our infra. Returning them as a
            # failure result instead of raising an ApplicationError keeps the
            # activity-level error tracking interceptor from capturing them as
            # if they were system bugs. `_record_export_failure` (called from
            # `export_asset_direct` before the re-raise) has already persisted
            # the exception, exception_type, and failure_type on ExportedAsset
            # so the user-facing toast and downstream code can still inspect
            # the failure.
            if exception_class in USER_QUERY_ERROR_NAMES:
                return ExportAssetResult(
                    exported_asset_id=asset.id,
                    success=False,
                    error=ExportError(
                        exception_class=exception_class,
                        error_trace=error_trace,
                        error_message=error_message,
                    ),
                )

            # Wrap in ApplicationError to propagate failure metadata as details while
            # preserving the exception class for retry-policy matching (transient CH/network
            # errors retry; programming errors and Chrome crashes fail fast). See
            # posthog.temporal.exports.types.extract_error_details. Strings are truncated so
            # an upstream exception can't blow out the 2 MiB payload envelope.
            raise ApplicationError(
                error_message,
                error_trace,
                type=exception_class,
                non_retryable=exception_class not in SYSTEM_ERROR_NAMES,
            ) from e

        await database_sync_to_async(asset.refresh_from_db, thread_sensitive=False)()

        return ExportAssetResult(
            exported_asset_id=asset.id,
            success=asset.has_content,
        )
