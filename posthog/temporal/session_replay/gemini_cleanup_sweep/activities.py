import asyncio
from dataclasses import replace
from datetime import UTC, datetime

from django.conf import settings

import structlog
from asgiref.sync import sync_to_async
from google.genai import Client as RawGenAIClient
from google.genai.errors import APIError
from temporalio import activity
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.client import async_connect
from posthog.temporal.session_replay.gemini_cleanup_sweep.constants import (
    DELETE_CONCURRENCY,
    DESCRIBE_CONCURRENCY,
    MAX_FILES_PER_SWEEP,
    SWEEP_MIN_AGE,
)
from posthog.temporal.session_replay.gemini_cleanup_sweep.tracking import (
    index_size,
    iter_tracked_files,
    untrack_uploaded_file,
)
from posthog.temporal.session_replay.gemini_cleanup_sweep.types import (
    CleanupSweepInputs,
    CleanupSweepResult,
    TrackedFile,
)

logger = structlog.get_logger(__name__)

_TERMINAL_STATUSES = frozenset(
    {
        WorkflowExecutionStatus.COMPLETED,
        WorkflowExecutionStatus.FAILED,
        WorkflowExecutionStatus.CANCELED,
        WorkflowExecutionStatus.TERMINATED,
        WorkflowExecutionStatus.TIMED_OUT,
    }
)


async def _classify_workflow(temporal: Client, workflow_id: str) -> str:
    """Returns ``"delete"``, ``"running"``, or ``"error"``."""
    try:
        desc = await temporal.get_workflow_handle(workflow_id).describe()
    except RPCError as e:
        if e.status == RPCStatusCode.NOT_FOUND:
            return "delete"
        return "error"
    except Exception:
        return "error"

    if desc.status in _TERMINAL_STATUSES:
        return "delete"
    return "running"


@activity.defn
async def sweep_gemini_files_activity(inputs: CleanupSweepInputs) -> CleanupSweepResult:
    """Reclaims orphaned Gemini files. Failures counted, never raised."""
    raw_client = RawGenAIClient(api_key=settings.GEMINI_API_KEY)
    temporal = await async_connect()
    cutoff = datetime.now(UTC) - SWEEP_MIN_AGE

    total_tracked = await index_size()
    hit_max_files_cap = total_tracked > MAX_FILES_PER_SWEEP

    scanned = 0
    skipped_too_young = 0
    skipped_invalid_value = 0
    candidates: list[TrackedFile] = []
    async for tracked in iter_tracked_files(limit=MAX_FILES_PER_SWEEP):
        scanned += 1
        if tracked is None:
            skipped_invalid_value += 1
            continue
        if tracked.uploaded_at > cutoff:
            skipped_too_young += 1
            continue
        candidates.append(tracked)
    activity.heartbeat({"phase": "scanned", "scanned": scanned, "candidates": len(candidates)})

    describe_sem = asyncio.Semaphore(DESCRIBE_CONCURRENCY)

    async def _classify(tracked: TrackedFile) -> tuple[TrackedFile, str]:
        async with describe_sem:
            outcome = await _classify_workflow(temporal, tracked.workflow_id)
            return tracked, outcome

    classifications = await asyncio.gather(*(_classify(t) for t in candidates))
    activity.heartbeat({"phase": "classified", "classified": len(classifications)})

    to_delete = [t for t, outcome in classifications if outcome == "delete"]
    skipped_running = sum(1 for _, outcome in classifications if outcome == "running")
    skipped_temporal_error = sum(1 for _, outcome in classifications if outcome == "error")

    base_result = CleanupSweepResult(
        scanned=scanned,
        skipped_too_young=skipped_too_young,
        skipped_invalid_value=skipped_invalid_value,
        skipped_running=skipped_running,
        skipped_temporal_error=skipped_temporal_error,
        hit_max_files_cap=hit_max_files_cap,
    )

    delete_sem = asyncio.Semaphore(DELETE_CONCURRENCY)

    async def _delete(tracked: TrackedFile) -> bool:
        async with delete_sem:
            try:
                await sync_to_async(raw_client.files.delete, thread_sensitive=False)(name=tracked.gemini_file_name)
            except APIError as e:
                if e.code == 404:
                    # File already gone (e.g., a previous untrack failed). Drop the key so we
                    # don't keep retrying a doomed delete.
                    logger.info(
                        "cleanup_sweep.delete_already_gone",
                        gemini_file_name=tracked.gemini_file_name,
                        workflow_id=tracked.workflow_id,
                        signals_type="cleanup-sweep",
                    )
                    await untrack_uploaded_file(tracked.gemini_file_name)
                    return True
                logger.exception(
                    "cleanup_sweep.delete_failed",
                    gemini_file_name=tracked.gemini_file_name,
                    workflow_id=tracked.workflow_id,
                    signals_type="cleanup-sweep",
                )
                return False
            except Exception:
                # Key kept for next-cycle retry; 48h TTL backstops.
                logger.exception(
                    "cleanup_sweep.delete_failed",
                    gemini_file_name=tracked.gemini_file_name,
                    workflow_id=tracked.workflow_id,
                    signals_type="cleanup-sweep",
                )
                return False
            await untrack_uploaded_file(tracked.gemini_file_name)
            return True

    delete_results = await asyncio.gather(*(_delete(t) for t in to_delete))
    deleted = sum(1 for r in delete_results if r)
    delete_failed = sum(1 for r in delete_results if not r)

    result = replace(base_result, deleted=deleted, delete_failed=delete_failed)
    logger.info(
        "cleanup_sweep.cycle_complete",
        scanned=result.scanned,
        deleted=result.deleted,
        skipped_running=result.skipped_running,
        skipped_too_young=result.skipped_too_young,
        skipped_invalid_value=result.skipped_invalid_value,
        skipped_temporal_error=result.skipped_temporal_error,
        delete_failed=result.delete_failed,
        hit_max_files_cap=result.hit_max_files_cap,
        signals_type="cleanup-sweep",
    )
    return result
