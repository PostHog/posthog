import asyncio
from dataclasses import replace
from datetime import UTC, datetime

from django.conf import settings

import structlog
from asgiref.sync import sync_to_async
from google.genai import (
    Client as RawGenAIClient,
    types,
)
from temporalio import activity
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.client import async_connect
from posthog.temporal.session_replay.session_summary.cleanup_sweep.constants import (
    AGE_THRESHOLD,
    DELETE_CONCURRENCY,
    DESCRIBE_CONCURRENCY,
    LIST_PAGE_SIZE,
    MAX_FILES_PER_SWEEP,
    display_name_prefix_for,
)
from posthog.temporal.session_replay.session_summary.cleanup_sweep.models import CleanupSweepInputs, CleanupSweepResult

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


def _list_candidates(
    raw_client: RawGenAIClient, cutoff: datetime, deployment: str
) -> tuple[int, int, int, int, list[tuple[str, str]], bool]:
    """Returns ``(listed, age_skipped, prefix_skipped, no_name_skipped, candidates, hit_cap)``.

    Sync because ``Pager`` is sync; call via ``sync_to_async``.
    """
    full_prefix = display_name_prefix_for(deployment)
    deployment_prefix = f"{deployment}:"
    listed = 0
    age_skipped = 0
    prefix_skipped = 0
    no_name_skipped = 0
    candidates: list[tuple[str, str]] = []
    hit_cap = False

    pager = raw_client.files.list(config=types.ListFilesConfig(page_size=LIST_PAGE_SIZE))
    for f in pager:
        listed += 1
        if f.create_time is None or f.create_time > cutoff:
            age_skipped += 1
            continue
        if not f.display_name or not f.display_name.startswith(full_prefix):
            prefix_skipped += 1
            continue
        if not f.name:
            # Owned by us per display_name, but unusable — surface separately for ops.
            no_name_skipped += 1
            continue
        workflow_id = f.display_name[len(deployment_prefix) :]
        candidates.append((f.name, workflow_id))
        if len(candidates) >= MAX_FILES_PER_SWEEP:
            hit_cap = True
            break
    return listed, age_skipped, prefix_skipped, no_name_skipped, candidates, hit_cap


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
    """Reclaims orphaned Gemini files. Failures are counted, never raised."""
    if not settings.CLOUD_DEPLOYMENT:
        raise RuntimeError("cleanup sweep requires CLOUD_DEPLOYMENT to be set")
    raw_client = RawGenAIClient(api_key=settings.GEMINI_API_KEY)
    temporal = await async_connect()
    cutoff = datetime.now(UTC) - AGE_THRESHOLD

    listed, age_skipped, prefix_skipped, no_name_skipped, candidates, hit_cap = await sync_to_async(
        _list_candidates, thread_sensitive=False
    )(raw_client, cutoff, settings.CLOUD_DEPLOYMENT)
    activity.heartbeat({"phase": "listed", "listed": listed, "candidates": len(candidates)})

    describe_sem = asyncio.Semaphore(DESCRIBE_CONCURRENCY)

    async def _classify_with_sem(file_name: str, workflow_id: str) -> tuple[str, str]:
        async with describe_sem:
            outcome = await _classify_workflow(temporal, workflow_id)
            return file_name, outcome

    classifications = await asyncio.gather(
        *(_classify_with_sem(fn, wid) for fn, wid in candidates),
    )
    activity.heartbeat({"phase": "classified", "classified": len(classifications)})

    to_delete = [fn for fn, outcome in classifications if outcome == "delete"]
    skipped_running = sum(1 for _, outcome in classifications if outcome == "running")
    skipped_error = sum(1 for _, outcome in classifications if outcome == "error")

    base_result = CleanupSweepResult(
        listed=listed,
        skipped_too_young=age_skipped,
        skipped_unrecognized_prefix=prefix_skipped,
        skipped_no_name=no_name_skipped,
        skipped_running=skipped_running,
        skipped_temporal_error=skipped_error,
        hit_max_files_cap=hit_cap,
        dry_run=inputs.dry_run,
    )

    if inputs.dry_run:
        logger.info(
            "cleanup_sweep.dry_run.would_delete",
            count=len(to_delete),
            listed=listed,
            signals_type="cleanup-sweep",
        )
        return replace(base_result, deleted=len(to_delete))

    delete_sem = asyncio.Semaphore(DELETE_CONCURRENCY)

    async def _delete(file_name: str) -> bool:
        async with delete_sem:
            try:
                await sync_to_async(raw_client.files.delete, thread_sensitive=False)(name=file_name)
                return True
            except Exception:
                logger.exception(
                    "cleanup_sweep.delete_failed",
                    gemini_file_name=file_name,
                    signals_type="cleanup-sweep",
                )
                return False

    delete_results = await asyncio.gather(*(_delete(fn) for fn in to_delete))
    deleted = sum(1 for r in delete_results if r)
    delete_failed = sum(1 for r in delete_results if not r)

    result = replace(base_result, deleted=deleted, delete_failed=delete_failed)
    logger.info(
        "cleanup_sweep.cycle_complete",
        listed=result.listed,
        deleted=result.deleted,
        skipped_running=result.skipped_running,
        skipped_too_young=result.skipped_too_young,
        skipped_unrecognized_prefix=result.skipped_unrecognized_prefix,
        skipped_no_name=result.skipped_no_name,
        skipped_temporal_error=result.skipped_temporal_error,
        delete_failed=result.delete_failed,
        hit_max_files_cap=result.hit_max_files_cap,
        signals_type="cleanup-sweep",
    )
    return result
