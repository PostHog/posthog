import datetime as dt
import dataclasses

from django.utils import timezone

from structlog import get_logger
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.sync import database_sync_to_async_pool

from products.data_modeling.backend.facade.api import upstream_tables_being_replaced
from products.data_modeling.backend.facade.models import DataModelingJob, Node

from .create_data_modeling_job import UPSTREAM_NAMES_IN_SKIP_REASON

LOGGER = get_logger(__name__)

# A sync run that is still Running after this long has stopped without finishing its job row.
STALE_RELOAD_AGE = dt.timedelta(days=3)


@dataclasses.dataclass(frozen=True, kw_only=True)
class CheckUpstreamReloadsInputs:
    team_id: int
    dag_id: str
    node_id: str
    # When set, a run that has to wait writes a Skipped job on this engine, so the wait is visible.
    skipped_job_engine: str | None = None
    parent_workflow_id: str | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class CheckUpstreamReloadsResult:
    """``reason`` is None when no upstream table is being loaded again."""

    reason: str | None = None
    skipped_job_id: str | None = None


def _reason(table_names: list[str]) -> str:
    shown = table_names[:UPSTREAM_NAMES_IN_SKIP_REASON]
    extra = len(table_names) - len(shown)
    if extra > 0:
        subject = f"tables {', '.join(shown)} and {extra} more"
    elif len(shown) > 1:
        subject = f"tables {', '.join(shown[:-1])} and {shown[-1]}"
    else:
        subject = f"table {shown[0]}"
    return (
        f"Skipped because a sync is loading the upstream {subject} again from the start. "
        "The view keeps its previous data and runs again when the sync finishes."
    )


@database_sync_to_async_pool
def _check_upstream_reloads(
    inputs: CheckUpstreamReloadsInputs, workflow_id: str, workflow_run_id: str
) -> CheckUpstreamReloadsResult:
    node = Node.objects.select_related("saved_query").get(
        id=inputs.node_id, team_id=inputs.team_id, dag_id=inputs.dag_id
    )
    if node.saved_query_id is None:
        return CheckUpstreamReloadsResult()
    table_names = upstream_tables_being_replaced(
        inputs.team_id, node.saved_query_id, started_after=timezone.now() - STALE_RELOAD_AGE
    )
    if not table_names:
        return CheckUpstreamReloadsResult()
    reason = _reason(table_names)
    if inputs.skipped_job_engine is None:
        return CheckUpstreamReloadsResult(reason=reason)
    job = DataModelingJob.objects.create(
        team_id=inputs.team_id,
        saved_query_id=node.saved_query_id,
        status=DataModelingJob.Status.SKIPPED,
        engine=inputs.skipped_job_engine,
        rows_materialized=0,
        error=reason,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        parent_workflow_id=inputs.parent_workflow_id,
        created_by_id=node.saved_query.created_by_id if node.saved_query else None,
    )
    return CheckUpstreamReloadsResult(reason=reason, skipped_job_id=str(job.id))


@activity.defn
async def check_upstream_reloads_activity(inputs: CheckUpstreamReloadsInputs) -> CheckUpstreamReloadsResult:
    """Whether a sync is loading a table this node reads again from empty.

    A full refresh or a reset overwrites the table with its first batch and appends the rest, so
    for the whole run the table holds only part of its rows. A materialization in that window
    would serve the partial result until its next run.
    """
    bind_contextvars(team_id=inputs.team_id)
    workflow_id = activity.info().workflow_id
    workflow_run_id = activity.info().workflow_run_id
    assert workflow_id
    assert workflow_run_id
    result = await _check_upstream_reloads(inputs, workflow_id, workflow_run_id)
    if result.reason is not None:
        await LOGGER.ainfo(
            "Upstream table is being loaded again",
            node_id=inputs.node_id,
            dag_id=inputs.dag_id,
            skipped_job_id=result.skipped_job_id,
        )
    return result
