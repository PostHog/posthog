import dataclasses

from structlog import get_logger
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.client import async_connect

from products.data_modeling.backend.facade.models import DataModelingJob, DataModelingJobStatus

LOGGER = get_logger(__name__)

PREEMPTED_ERROR = "Preempted: a new DAG run started before this job completed"


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
def _get_running_jobs_for_dag(team_id: int, dag_id: str, node_ids: list[str] | None) -> list[DataModelingJob]:
    """Find RUNNING DataModelingJob records belonging to a previous run of *these* nodes.

    Child workflow IDs follow the pattern `materialize-view-{dag_id}-{node_id}-{timestamp}`,
    so we can match jobs by their workflow_id prefix.

    Cadence tiers of one DAG hold disjoint node sets and run on their own schedules, so a tier
    must only preempt its own nodes — matching on `dag_id` alone lets one tier cancel another
    tier's unrelated in-flight work. An unset `node_ids` means a whole-DAG run (the legacy
    single v2 schedule), which owns every node and preempts accordingly.
    """
    jobs = DataModelingJob.objects.filter(
        team_id=team_id,
        status=DataModelingJobStatus.RUNNING,
        workflow_id__startswith=f"materialize-view-{dag_id}-",
    )
    # Empty means "every node", matching how ExecuteDAGWorkflow reads the same field.
    if not node_ids:
        return list(jobs)
    owned = set(node_ids)
    return [job for job in jobs if _node_id_from_workflow_id(job.workflow_id or "", dag_id) in owned]


@database_sync_to_async_pool
def _mark_jobs_as_preempted(job_ids: list[str]) -> int:
    return DataModelingJob.objects.filter(id__in=job_ids, status=DataModelingJobStatus.RUNNING).update(
        status=DataModelingJobStatus.FAILED,
        rows_materialized=0,
        error=PREEMPTED_ERROR,
    )


@activity.defn
async def preempt_dag_run_activity(inputs: PreemptDAGRunInputs) -> None:
    """Preempt in-flight materializations of the nodes this run is about to materialize.

    Cancels each owned node's own MaterializeViewWorkflow rather than the parent
    ExecuteDAGWorkflow: parent cancellation cascades to every sibling child via
    ParentClosePolicy.REQUEST_CANCEL, so preempting one node that has since moved between
    cadence tiers would take down the whole run that still owns its siblings.
    A parent starts each of its nodes once, so there is no child to re-spawn behind us.
    """
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    running_jobs = await _get_running_jobs_for_dag(inputs.team_id, inputs.dag_id, inputs.node_ids)
    if not running_jobs:
        await logger.adebug("No previous DAG run to preempt")
        return

    await logger.ainfo(
        f"Preempting previous DAG run: found {len(running_jobs)} running jobs",
        dag_id=inputs.dag_id,
    )
    child_workflow_ids = {job.workflow_id for job in running_jobs if job.workflow_id}
    job_ids = [str(job.id) for job in running_jobs]
    updated_count = await _mark_jobs_as_preempted(job_ids)
    await logger.ainfo(f"Marked {updated_count} jobs as preempted", dag_id=inputs.dag_id)
    if child_workflow_ids:
        try:
            temporal = await async_connect()
            for workflow_id in child_workflow_ids:
                try:
                    handle = temporal.get_workflow_handle(workflow_id)
                    await handle.cancel()
                    await logger.ainfo(f"Requested cancellation of materialize workflow {workflow_id}")
                except Exception as e:
                    # workflow may have already completed — that's fine
                    await logger.awarning(f"Could not cancel materialize workflow {workflow_id}: {str(e)}")
        except Exception as e:
            capture_exception(e)
            await logger.aexception(f"Failed to connect to Temporal for workflow cancellation: {str(e)}")
