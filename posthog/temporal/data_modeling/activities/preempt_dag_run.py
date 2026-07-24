import datetime as dt
import dataclasses

from django.utils import timezone

from structlog import get_logger
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.client import async_connect

from products.data_modeling.backend.facade.models import DataModelingJob, DataModelingJobStatus

LOGGER = get_logger(__name__)

PREEMPTED_ERROR = "Preempted: a new DAG run started before this job completed"
ABANDONED_ERROR = "Abandoned: the materialization workflow is no longer running"

# A MaterializeViewWorkflow's activities cap out at 20 minutes with a 2-minute heartbeat, so a row
# still marked Running well past that has lost its workflow and will never close itself. Kept
# deliberately loose: over-waiting only delays cleanup, while under-waiting would fail a live job.
STALE_RUNNING_JOB_AGE = dt.timedelta(hours=6)


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
    jobs: list[DataModelingJob], dag_id: str, node_ids: list[str] | None, now: dt.datetime
) -> tuple[list[DataModelingJob], list[DataModelingJob]]:
    """Split this DAG's running jobs into the ones we preempt and the ones we merely reap.

    Two different jobs share this activity, and they want different scopes:

    - *Preempt* the nodes this run is about to materialize. Cadence tiers of one DAG hold
      disjoint node sets, so preempting DAG-wide lets one tier cancel another tier's live work.
      An unset `node_ids` means a whole-DAG run (the legacy single v2 schedule), which owns
      every node.
    - *Reap* rows left behind by a workflow that is long gone, wherever they are in the DAG.
      Those are corpses, not work in progress, so ownership must not gate cleaning them up —
      a node in no tier is otherwise stuck Running forever. Gating on age is what keeps this
      from touching another tier's live job.
    """
    owned = set(node_ids or [])
    stale_before = now - STALE_RUNNING_JOB_AGE
    ours: list[DataModelingJob] = []
    abandoned: list[DataModelingJob] = []
    for job in jobs:
        # Empty node_ids means "every node", matching how ExecuteDAGWorkflow reads the same field.
        if not node_ids or _node_id_from_workflow_id(job.workflow_id or "", dag_id) in owned:
            ours.append(job)
        # No timestamp means we cannot prove the row is a corpse, so leave it running.
        elif job.updated_at is not None and job.updated_at < stale_before:
            abandoned.append(job)
    return ours, abandoned


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

    Reaped rows are only marked, never cancelled — there is no live workflow left to cancel,
    and cancelling on another tier's behalf is exactly what this activity must not do.
    """
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    running_jobs = await _get_running_jobs_for_dag(inputs.team_id, inputs.dag_id)
    ours, abandoned = partition_running_jobs(running_jobs, inputs.dag_id, inputs.node_ids, timezone.now())
    if not ours and not abandoned:
        await logger.adebug("No previous DAG run to preempt")
        return

    if abandoned:
        reaped = await _mark_jobs_failed([str(job.id) for job in abandoned], ABANDONED_ERROR)
        await logger.ainfo(f"Reaped {reaped} abandoned jobs", dag_id=inputs.dag_id)

    if not ours:
        return

    await logger.ainfo(
        f"Preempting previous DAG run: found {len(ours)} running jobs",
        dag_id=inputs.dag_id,
    )
    child_workflow_ids = {job.workflow_id for job in ours if job.workflow_id}
    updated_count = await _mark_jobs_failed([str(job.id) for job in ours], PREEMPTED_ERROR)
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
