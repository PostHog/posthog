import dataclasses

from structlog import get_logger
from structlog.contextvars import bind_contextvars
from temporalio import activity
from temporalio.client import Client, WorkflowExecutionStatus

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.client import async_connect

from products.data_modeling.backend.facade.models import DataModelingJob, DataModelingJobStatus

LOGGER = get_logger(__name__)

PREEMPTED_ERROR = "Preempted: a new DAG run started before this job completed"
ABANDONED_ERROR = "Abandoned: the materialization workflow is no longer running"


@dataclasses.dataclass
class PreemptDAGRunInputs:
    team_id: int
    dag_id: str
    node_ids: list[str] | None = None


def _node_id_from_workflow_id(workflow_id: str, dag_id: str) -> str | None:
    """Recover the node id from a child workflow id, or None if it doesn't belong to this DAG."""
    prefix = f"materialize-view-{dag_id}-"
    if not workflow_id.startswith(prefix):
        return None
    # The remainder is `{node_id}-{timestamp}`. Node ids are UUIDs, so take the first five
    # dash-separated groups rather than assuming a fixed overall length.
    groups = workflow_id[len(prefix) :].split("-")
    return "-".join(groups[:5]) if len(groups) >= 5 else None


@database_sync_to_async_pool
def _get_running_jobs_for_dag(team_id: int, dag_id: str) -> list[DataModelingJob]:
    """Every RUNNING job belonging to this DAG, whether or not this run owns its node.

    Child workflow IDs follow the pattern `materialize-view-{dag_id}-{node_id}-{timestamp}`,
    so we can match jobs by their workflow_id prefix.
    """
    return list(
        DataModelingJob.objects.filter(
            team_id=team_id,
            status=DataModelingJobStatus.RUNNING,
            workflow_id__startswith=f"materialize-view-{dag_id}-",
        )
    )


def partition_running_jobs(
    jobs: list[DataModelingJob], dag_id: str, node_ids: list[str] | None
) -> tuple[list[DataModelingJob], list[DataModelingJob]]:
    """Split this DAG's running jobs into the nodes this run owns and everything else.

    Cadence tiers of one DAG hold disjoint node sets, so only the owned half may be preempted —
    preempting DAG-wide is what lets one tier cancel another tier's live work. An unset
    `node_ids` means a whole-DAG run (the legacy single v2 schedule), which owns every node.

    The rest are merely *candidates* for reaping: whether they are corpses is decided by asking
    Temporal, not by anything on the row.
    """
    owned = set(node_ids or [])
    ours: list[DataModelingJob] = []
    others: list[DataModelingJob] = []
    for job in jobs:
        # Empty node_ids means "every node", matching how ExecuteDAGWorkflow reads the same field.
        if not node_ids or _node_id_from_workflow_id(job.workflow_id or "", dag_id) in owned:
            ours.append(job)
        else:
            others.append(job)
    return ours, others


async def _abandoned_jobs(temporal: Client, candidates: list[DataModelingJob]) -> list[DataModelingJob]:
    """Of these rows, the ones whose workflow is no longer running.

    A row saying Running while its workflow is closed (or gone from Temporal's retention) is a
    corpse: nothing will ever close it. Asking Temporal is the only way to tell a corpse from a
    slow run — a job's wall-clock age cannot, because nothing bounds it. Activity
    `start_to_close_timeout` caps one attempt, not queue wait, retries, or the workflow overall,
    and MaterializeViewWorkflow is started with no execution timeout.
    """
    abandoned: list[DataModelingJob] = []
    for job in candidates:
        if not job.workflow_id:
            continue
        try:
            description = await temporal.get_workflow_handle(job.workflow_id).describe()
        except Exception:
            # Not found: Temporal has no record of it, so nothing is running.
            abandoned.append(job)
            continue
        if description.status != WorkflowExecutionStatus.RUNNING:
            abandoned.append(job)
    return abandoned


@database_sync_to_async_pool
def _mark_jobs_failed(job_ids: list[str], error: str) -> int:
    return DataModelingJob.objects.filter(id__in=job_ids, status=DataModelingJobStatus.RUNNING).update(
        status=DataModelingJobStatus.FAILED,
        rows_materialized=0,
        error=error,
    )


@activity.defn
async def preempt_dag_run_activity(inputs: PreemptDAGRunInputs) -> None:
    """Preempt in-flight materializations of the nodes this run is about to materialize, and
    reap rows anywhere in the DAG whose workflow died without closing them.

    Cancels each owned node's own MaterializeViewWorkflow rather than the parent
    ExecuteDAGWorkflow: parent cancellation cascades to every sibling child via
    ParentClosePolicy.REQUEST_CANCEL, so preempting one node that has since moved between
    cadence tiers would take down the whole run that still owns its siblings.
    A parent starts each of its nodes once, so there is no child to re-spawn behind us.

    Rows outside that node set are only reaped, and only once Temporal confirms their workflow
    is no longer running: they are marked, never cancelled, because there is nothing left to
    cancel and cancelling on another tier's behalf is exactly what this activity must not do.
    """
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    running_jobs = await _get_running_jobs_for_dag(inputs.team_id, inputs.dag_id)
    ours, others = partition_running_jobs(running_jobs, inputs.dag_id, inputs.node_ids)
    if not ours and not others:
        await logger.adebug("No previous DAG run to preempt")
        return

    if ours:
        await logger.ainfo(
            f"Preempting previous DAG run: found {len(ours)} running jobs",
            dag_id=inputs.dag_id,
        )
        updated_count = await _mark_jobs_failed([str(job.id) for job in ours], PREEMPTED_ERROR)
        await logger.ainfo(f"Marked {updated_count} jobs as preempted", dag_id=inputs.dag_id)

    try:
        temporal = await async_connect()
    except Exception as e:
        # The preemption marks above already landed; without a client we can neither cancel
        # nor prove anything is abandoned, so leave the rest for the next run.
        capture_exception(e)
        await logger.aexception(f"Failed to connect to Temporal: {str(e)}")
        return

    if others:
        abandoned = await _abandoned_jobs(temporal, others)
        if abandoned:
            reaped = await _mark_jobs_failed([str(job.id) for job in abandoned], ABANDONED_ERROR)
            await logger.ainfo(f"Reaped {reaped} abandoned jobs", dag_id=inputs.dag_id)

    for workflow_id in {job.workflow_id for job in ours if job.workflow_id}:
        try:
            await temporal.get_workflow_handle(workflow_id).cancel()
            await logger.ainfo(f"Requested cancellation of materialize workflow {workflow_id}")
        except Exception as e:
            # workflow may have already completed — that's fine
            await logger.awarning(f"Could not cancel materialize workflow {workflow_id}: {str(e)}")
