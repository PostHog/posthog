import asyncio
import threading
import traceback

import structlog
import temporalio.activity
from prometheus_client import Counter
from temporalio.exceptions import ApplicationError

from posthog.event_usage import EventSource
from posthog.sync import database_sync_to_async
from posthog.tasks import exporter
from posthog.temporal.common.errors import (
    MAX_ERROR_MESSAGE_CHARS,
    MAX_ERROR_TRACE_CHARS,
    NonReportableApplicationError,
    truncate_for_temporal_payload,
)
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.exports.types import (
    ExportAssetActivityInputs,
    ExportAssetResult,
    ExportAssetsBatchActivityInputs,
    ExportAssetsBatchResult,
    ExportError,
    export_failure_metadata,
)

from products.exports.backend.models.exported_asset import ExportedAsset
from products.exports.backend.tasks.failure_handler import (
    SYSTEM_ERROR_NAMES,
    TIMEOUT_ERROR_NAMES,
    ExportCancelled,
    export_slo_failure_details,
    is_reportable_export_failure,
)

logger = structlog.get_logger(__name__)

EXPORT_BATCH_HANDOFF_COUNTER = Counter(
    "image_export_batch_handoffs_total",
    "Assets a batched render could not finish and handed back for a per-asset export with retries",
)

# Render/query timeouts are transient and must stay retryable; an explicit
# cancellation is terminal even though it lives in TIMEOUT_ERROR_NAMES.
RETRYABLE_ERROR_NAMES = SYSTEM_ERROR_NAMES | (TIMEOUT_ERROR_NAMES - {ExportCancelled.__name__})


def _is_retryable_export_failure(error: Exception) -> bool:
    return type(error).__name__ in RETRYABLE_ERROR_NAMES


def _export_failure_trace(error: Exception) -> str:
    return truncate_for_temporal_payload("\n".join(traceback.format_exception(error)[:5]), MAX_ERROR_TRACE_CHARS)


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
            try:
                await database_sync_to_async(asset.refresh_from_db, thread_sensitive=False)()
            except Exception as refresh_error:
                # Preserve the export error because it determines the SLO classification.
                logger.warning(
                    "export_asset_activity.refresh_after_failure_failed",
                    exported_asset_id=asset.id,
                    team_id=asset.team_id,
                    exception_class=type(refresh_error).__name__,
                    error=str(refresh_error),
                    exc_info=True,
                )
            exception_class = type(e).__name__
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
            # A user query error is not a defect, so it stays out of error tracking.
            error_class = ApplicationError if is_reportable_export_failure(e) else NonReportableApplicationError
            raise error_class(
                truncate_for_temporal_payload(str(e), MAX_ERROR_MESSAGE_CHARS),
                _export_failure_trace(e),
                export_failure_metadata(export_slo_failure_details(e)),
                type=exception_class,
                non_retryable=not _is_retryable_export_failure(e),
            ) from e

        await database_sync_to_async(asset.refresh_from_db, thread_sensitive=False)()

        return ExportAssetResult(
            exported_asset_id=asset.id,
            success=asset.has_content,
        )


def _settled_failure(exported_asset_id: int, error: Exception) -> ExportAssetResult:
    return ExportAssetResult(
        exported_asset_id=exported_asset_id,
        success=False,
        error=ExportError(
            exception_class=type(error).__name__,
            error_trace=_export_failure_trace(error),
            failure_details=export_slo_failure_details(error),
        ),
    )


@temporalio.activity.defn
async def export_assets_batch_activity(inputs: ExportAssetsBatchActivityInputs) -> ExportAssetsBatchResult:
    async with Heartbeater():
        assets_by_id = await database_sync_to_async(
            lambda: ExportedAsset.objects_including_ttl_deleted.select_related(
                "created_by", "team", "team__organization", "insight", "dashboard"
            ).in_bulk(inputs.exported_asset_ids),
            thread_sensitive=False,
        )()
        assets = [assets_by_id[asset_id] for asset_id in inputs.exported_asset_ids if asset_id in assets_by_id]

        logger.info(
            "export_assets_batch_activity.starting",
            exported_asset_ids=inputs.exported_asset_ids,
            asset_count=len(assets),
        )

        stop = threading.Event()
        try:
            failures = await database_sync_to_async(exporter.export_image_assets_batched, thread_sensitive=False)(
                assets,
                source=EventSource(inputs.source) if inputs.source else None,
                should_stop=stop.is_set,
            )
        except asyncio.CancelledError:
            stop.set()
            raise

        settled: list[ExportAssetResult] = []
        for asset in assets:
            failure = failures.get(asset.id)
            if failure is None:
                settled.append(ExportAssetResult(exported_asset_id=asset.id, success=asset.has_content))
            elif not _is_retryable_export_failure(failure):
                settled.append(_settled_failure(asset.id, failure))

        handed_back = len(inputs.exported_asset_ids) - len(settled)
        EXPORT_BATCH_HANDOFF_COUNTER.inc(handed_back)
        logger.info(
            "export_assets_batch_activity.finished",
            exported_asset_ids=inputs.exported_asset_ids,
            succeeded=sum(result.success for result in settled),
            failed=sum(not result.success for result in settled),
            handed_back=handed_back,
        )
        return ExportAssetsBatchResult(settled=settled)
