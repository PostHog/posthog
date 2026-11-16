import asyncio

from django.conf import settings

import structlog
from asgiref.sync import async_to_sync
from temporalio.client import WorkflowExecutionStatus
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.client import async_connect

from ..facade.clustering_contracts import ClusteringRunRef, ClusteringRunUpdate
from ..logic.clustering.constants import FIRST_RUN_WORKFLOW
from ..logic.clustering.runs import update_run
from ..models.clustering_run import ClusteringRunStatus

logger = structlog.get_logger(__name__)


def dispatch_clustering_run(team_id: int, run_id: str) -> None:
    async def start() -> None:
        async with asyncio.timeout(10):
            client = await async_connect()
            await client.start_workflow(
                FIRST_RUN_WORKFLOW,
                ClusteringRunRef(team_id=team_id, run_id=run_id),
                id=f"ai-observability-clustering-first-run-{run_id}",
                task_queue=settings.LLMA_TASK_QUEUE,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )

    try:
        async_to_sync(start)()
    except WorkflowAlreadyStartedError:
        reconcile_clustering_run(team_id, run_id, f"ai-observability-clustering-first-run-{run_id}")
    except Exception:
        logger.exception("clustering_first_run_dispatch_failed", team_id=team_id, run_id=run_id)
        update_run(
            ClusteringRunUpdate(
                ref=ClusteringRunRef(team_id=team_id, run_id=run_id),
                status=ClusteringRunStatus.QUEUED,
                failure_reason="could_not_start",
            )
        )


def reconcile_clustering_run(team_id: int, run_id: str, workflow_id: str, *, cancel: bool = False) -> None:
    async def reconcile() -> bool:
        async with asyncio.timeout(10):
            client = await async_connect()
            handle = client.get_workflow_handle(workflow_id)
            try:
                if cancel:
                    await handle.cancel()
                    return False
                description = await handle.describe()
                if description.status == WorkflowExecutionStatus.RUNNING:
                    return False
            except RPCError as error:
                if error.status != RPCStatusCode.NOT_FOUND:
                    raise
            return not cancel

    if async_to_sync(reconcile)():
        update_run(
            ClusteringRunUpdate(
                ref=ClusteringRunRef(team_id=team_id, run_id=run_id),
                status=ClusteringRunStatus.FAILED,
                failure_reason="workflow_stopped",
            )
        )
