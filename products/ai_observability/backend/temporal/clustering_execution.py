import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.common.utils import on_asyncify_pool

    from ..facade.clustering_contracts import (
        ClusteringExecutionClaim,
        ClusteringExecutionRequest,
        ClusteringRunRef,
        ClusteringRunUpdate,
    )


@activity.defn
async def acquire_clustering_execution_activity(request: ClusteringExecutionRequest) -> ClusteringExecutionClaim | None:
    from ..facade import api

    return await on_asyncify_pool(api.acquire_clustering_execution)(request)


@activity.defn
async def finish_clustering_execution_activity(update: ClusteringRunUpdate) -> None:
    from ..facade import api

    await on_asyncify_pool(api.update_clustering_run)(update)


def require_current_execution(team_id: int, run_id: str) -> str:
    from ..facade import api

    if not run_id:
        if team_id not in api.eligible_clustering_team_ids([team_id]):
            raise ApplicationError("Clustering is no longer enabled", non_retryable=True)
        return ""
    scope = api.clustering_execution_scope(ClusteringRunRef(team_id=team_id, run_id=run_id))
    if scope is None:
        raise ApplicationError("Clustering run is no longer active", non_retryable=True)
    return scope


@asynccontextmanager
async def clustering_execution(
    team_id: int, job_id: str, analysis_level: str, event_filters: list[dict], run_id: str
) -> AsyncIterator[str | None]:
    if not job_id or not workflow.patched("clustering-job-execution-claim"):
        yield run_id
        return
    claim = await workflow.execute_activity(
        acquire_clustering_execution_activity,
        ClusteringExecutionRequest(
            team_id=team_id,
            job_id=job_id,
            analysis_level=analysis_level,
            event_filters=event_filters,
            workflow_id=workflow.info().workflow_id,
            run_id=run_id,
        ),
        start_to_close_timeout=timedelta(seconds=30),
        retry_policy=RetryPolicy(maximum_attempts=3),
    )
    if claim is None:
        yield None
        return
    status = "completed"
    try:
        yield claim.run_id
    except asyncio.CancelledError:
        status = "canceled"
        raise
    except Exception:
        status = "failed"
        raise
    finally:
        if claim.owned:
            await asyncio.shield(
                workflow.execute_activity(
                    finish_clustering_execution_activity,
                    ClusteringRunUpdate(ref=ClusteringRunRef(team_id=team_id, run_id=claim.run_id), status=status),
                    start_to_close_timeout=timedelta(seconds=30),
                )
            )
