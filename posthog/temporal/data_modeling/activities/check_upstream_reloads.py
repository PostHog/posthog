import datetime as dt
import dataclasses

from django.db.models import QuerySet
from django.utils import timezone

from structlog import get_logger
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.client import async_connect

from products.data_modeling.backend.facade.api import upstream_tables_being_replaced
from products.data_modeling.backend.facade.models import (
    DataModelingJob,
    DataModelingJobEngine,
    DataModelingJobStatus,
    Node,
)

from .create_data_modeling_job import UPSTREAM_NAMES_IN_SKIP_REASON
from .preempt_dag_run import _abandoned_jobs

LOGGER = get_logger(__name__)

# A sync run that is still Running after this long has stopped without finishing its job row.
STALE_RELOAD_AGE = dt.timedelta(days=3)


@dataclasses.dataclass(frozen=True, kw_only=True)
class CheckUpstreamReloadsInputs:
    team_id: int
    dag_id: str
    node_id: str
    engine: str = DataModelingJobEngine.CLICKHOUSE
    parent_workflow_id: str | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class CheckUpstreamReloadsResult:
    """``reason`` is None when no upstream table is being loaded again."""

    reason: str | None = None
    skipped_job_id: str | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class NodesWaitingOnUpstreamReloadsInputs:
    team_id: int
    dag_id: str
    node_ids: list[str]
    engine: str = DataModelingJobEngine.CLICKHOUSE


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


def _jobs(team_id: int, nodes: list[Node], engine: str) -> QuerySet[DataModelingJob]:
    saved_query_ids = [node.saved_query_id for node in nodes if node.saved_query_id is not None]
    return DataModelingJob.objects.filter(team_id=team_id, saved_query_id__in=saved_query_ids, engine=engine)


def _built_saved_query_ids(team_id: int, nodes: list[Node], engine: str) -> set:
    jobs = _jobs(team_id, nodes, engine).filter(status=DataModelingJobStatus.COMPLETED)
    return set(jobs.values_list("saved_query_id", flat=True).distinct())


def _tables_being_reloaded(node: Node, engine: str, built_saved_query_ids: set) -> list[str]:
    # With no complete data to keep serving, waiting gains nothing over a partial first build.
    if node.saved_query is None or node.saved_query_id not in built_saved_query_ids:
        return []
    if engine == DataModelingJobEngine.CLICKHOUSE and node.saved_query.table_id is None:
        return []
    return upstream_tables_being_replaced(
        node.team_id, node.saved_query_id, started_after=timezone.now() - STALE_RELOAD_AGE
    )


@database_sync_to_async_pool
def _skip_if_reloading(
    inputs: CheckUpstreamReloadsInputs, workflow_id: str, workflow_run_id: str
) -> CheckUpstreamReloadsResult:
    node = Node.objects.select_related("saved_query").get(
        id=inputs.node_id, team_id=inputs.team_id, dag_id=inputs.dag_id
    )
    table_names = _tables_being_reloaded(
        node, inputs.engine, _built_saved_query_ids(inputs.team_id, [node], inputs.engine)
    )
    if not table_names:
        return CheckUpstreamReloadsResult()
    reason = _reason(table_names)
    # An activity retry after the insert committed finds the row instead of writing a second one.
    job = DataModelingJob.objects.filter(
        team_id=inputs.team_id,
        saved_query_id=node.saved_query_id,
        engine=inputs.engine,
        status=DataModelingJobStatus.SKIPPED,
        workflow_run_id=workflow_run_id,
    ).first() or DataModelingJob.objects.create(
        team_id=inputs.team_id,
        saved_query_id=node.saved_query_id,
        status=DataModelingJobStatus.SKIPPED,
        engine=inputs.engine,
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
    """Write a Skipped job when a sync is loading a table this node reads again from empty.

    A full refresh or a reset overwrites the table with its first batch and appends the rest, so
    for the whole run the table holds only part of its rows. A materialization in that window
    would serve the partial result until its next run.
    """
    bind_contextvars(team_id=inputs.team_id)
    workflow_id = activity.info().workflow_id
    workflow_run_id = activity.info().workflow_run_id
    assert workflow_id
    assert workflow_run_id
    result = await _skip_if_reloading(inputs, workflow_id, workflow_run_id)
    if result.reason is not None:
        await LOGGER.ainfo(
            "Upstream table is being loaded again",
            node_id=inputs.node_id,
            dag_id=inputs.dag_id,
            skipped_job_id=result.skipped_job_id,
        )
    return result


@database_sync_to_async_pool
def _nodes_and_running_jobs(inputs: NodesWaitingOnUpstreamReloadsInputs) -> tuple[list[Node], list[DataModelingJob]]:
    nodes = list(
        Node.objects.filter(team_id=inputs.team_id, dag_id=inputs.dag_id, id__in=inputs.node_ids).select_related(
            "saved_query"
        )
    )
    running = list(_jobs(inputs.team_id, nodes, inputs.engine).filter(status=DataModelingJobStatus.RUNNING))
    return nodes, running


@database_sync_to_async_pool
def _any_node_reloading(nodes: list[Node], inputs: NodesWaitingOnUpstreamReloadsInputs) -> bool:
    built_saved_query_ids = _built_saved_query_ids(inputs.team_id, nodes, inputs.engine)
    # Stops at the first node still waiting, so a poll during a long reload reads little.
    return any(_tables_being_reloaded(node, inputs.engine, built_saved_query_ids) for node in nodes)


@activity.defn
async def any_node_waiting_on_upstream_reloads_activity(inputs: NodesWaitingOnUpstreamReloadsInputs) -> bool:
    """Whether any of these nodes waits on an upstream reload or on another run of it. Writes nothing."""
    bind_contextvars(team_id=inputs.team_id)
    nodes, running = await _nodes_and_running_jobs(inputs)
    # A node that another run is materializing waits too, so the follow-up never preempts that run.
    # Temporal decides which Running rows are live, because a job's age cannot tell a slow run from
    # a dead one.
    if running and len(await _abandoned_jobs(await async_connect(), running)) < len(running):
        return True
    return await _any_node_reloading(nodes, inputs)
