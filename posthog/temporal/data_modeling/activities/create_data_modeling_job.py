import dataclasses

from structlog import get_logger
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.sync import database_sync_to_async_pool
from posthog.temporal.data_modeling.activities.utils import bind_data_modeling_log_context

from products.data_modeling.backend.facade.models import DataModelingJob, DataModelingJobEngine, Node

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class CreateDataModelingJobInputs:
    team_id: int
    node_id: str
    dag_id: str
    engine: str = DataModelingJobEngine.CLICKHOUSE
    parent_workflow_id: str | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class CreatedDataModelingJob:
    job_id: str
    saved_query_id: str | None


UPSTREAM_NAMES_IN_SKIP_REASON = 3


@dataclasses.dataclass(frozen=True, kw_only=True)
class SkippedDataModelingNode:
    node_id: str
    # Only the ids the reason can name, plus how many there were. A node in a dense graph can
    # sit downstream of hundreds of broken ancestors, and the whole payload has to fit in one
    # Temporal activity argument.
    failed_upstream_node_ids: list[str] = dataclasses.field(default_factory=list)
    failed_upstream_total: int = 0
    suspended_upstream_node_ids: list[str] = dataclasses.field(default_factory=list)
    suspended_upstream_total: int = 0


@dataclasses.dataclass(frozen=True, kw_only=True)
class RecordSkippedDataModelingJobsInputs:
    team_id: int
    dag_id: str
    engine: str
    skipped_nodes: list[SkippedDataModelingNode]


@database_sync_to_async_pool
def _create_data_modeling_job(
    inputs: CreateDataModelingJobInputs, workflow_id: str, workflow_run_id: str
) -> CreatedDataModelingJob:
    node = Node.objects.prefetch_related("saved_query").get(
        id=inputs.node_id, team_id=inputs.team_id, dag_id=inputs.dag_id
    )
    job = DataModelingJob.objects.create(
        team_id=inputs.team_id,
        saved_query=node.saved_query,
        status=DataModelingJob.Status.RUNNING,
        engine=inputs.engine,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        parent_workflow_id=inputs.parent_workflow_id,
        created_by_id=node.saved_query.created_by_id if node.saved_query else None,
    )
    return CreatedDataModelingJob(
        job_id=str(job.id),
        saved_query_id=str(node.saved_query.id) if node.saved_query else None,
    )


@activity.defn
async def create_data_modeling_job_activity(inputs: CreateDataModelingJobInputs) -> str:
    """Create a DataModelingJob record in RUNNING status."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    workflow_id = activity.info().workflow_id
    workflow_run_id = activity.info().workflow_run_id

    # Will always be defined if this activity was started by a workflow
    assert workflow_id
    assert workflow_run_id

    created = await _create_data_modeling_job(inputs, workflow_id, workflow_run_id)
    if created.saved_query_id is not None:
        bind_data_modeling_log_context(inputs.team_id, created.saved_query_id)
    await logger.ainfo(f"Created DataModelingJob {created.job_id} for node {inputs.node_id}")
    return created.job_id


def _subject(names: list[str], total: int) -> str:
    """Name at most three upstreams and count the rest, so one broken source feeding a wide
    graph stays readable. Names can be missing if a node was deleted mid-run; the count still
    tells the truth about how many blocked this one."""
    shown = names[:UPSTREAM_NAMES_IN_SKIP_REASON]
    if not shown:
        return "an upstream view" if total <= 1 else f"{total} upstream views"
    noun = "upstream view" if total == 1 else "upstream views"
    extra = total - len(shown)
    if extra > 0:
        return f"{noun} {', '.join(shown)} and {extra} more"
    if len(shown) > 1:
        return f"{noun} {', '.join(shown[:-1])} and {shown[-1]}"
    return f"{noun} {shown[0]}"


def _skip_reason(*, failed: list[str], failed_total: int, suspended: list[str], suspended_total: int) -> str:
    if failed_total and suspended_total:
        subject = _subject(failed + suspended, failed_total + suspended_total)
        return f"Skipped because {subject} are failing or paused."
    if failed_total:
        verb = "is" if failed_total == 1 else "are"
        return f"Skipped because {_subject(failed, failed_total)} {verb} failing."
    if suspended_total:
        verb = "was" if suspended_total == 1 else "were"
        return f"Skipped because {_subject(suspended, suspended_total)} {verb} paused after repeated failures."
    return "Skipped because an upstream view failed."


@database_sync_to_async_pool
def _record_skipped_data_modeling_jobs(
    inputs: RecordSkippedDataModelingJobsInputs, workflow_id: str, workflow_run_id: str
) -> None:
    node_ids = {skipped.node_id for skipped in inputs.skipped_nodes} | {
        upstream_id
        for skipped in inputs.skipped_nodes
        for upstream_id in skipped.failed_upstream_node_ids + skipped.suspended_upstream_node_ids
    }
    nodes = {
        str(node.id): node
        for node in Node.objects.filter(team_id=inputs.team_id, dag_id=inputs.dag_id, id__in=node_ids).select_related(
            "saved_query"
        )
    }
    skipped_nodes = [nodes[skipped.node_id] for skipped in inputs.skipped_nodes if skipped.node_id in nodes]
    saved_query_ids = {node.saved_query_id for node in skipped_nodes if node.saved_query_id is not None}
    existing_saved_query_ids = set(
        DataModelingJob.objects.filter(
            team_id=inputs.team_id,
            engine=inputs.engine,
            parent_workflow_id=workflow_id,
            saved_query_id__in=saved_query_ids,
        ).values_list("saved_query_id", flat=True)
    )

    jobs = []
    for skipped in inputs.skipped_nodes:
        node = nodes.get(skipped.node_id)
        if node is None or node.saved_query_id is None or node.saved_query_id in existing_saved_query_ids:
            continue
        jobs.append(
            DataModelingJob(
                team_id=inputs.team_id,
                saved_query_id=node.saved_query_id,
                status=DataModelingJob.Status.SKIPPED,
                engine=inputs.engine,
                rows_materialized=0,
                error=_skip_reason(
                    failed=[nodes[i].name for i in skipped.failed_upstream_node_ids if i in nodes],
                    failed_total=skipped.failed_upstream_total,
                    suspended=[nodes[i].name for i in skipped.suspended_upstream_node_ids if i in nodes],
                    suspended_total=skipped.suspended_upstream_total,
                ),
                workflow_id=workflow_id,
                workflow_run_id=workflow_run_id,
                parent_workflow_id=workflow_id,
                created_by_id=node.saved_query.created_by_id if node.saved_query else None,
            )
        )
        existing_saved_query_ids.add(node.saved_query_id)
    DataModelingJob.objects.bulk_create(jobs)


@activity.defn
async def record_skipped_data_modeling_jobs_activity(inputs: RecordSkippedDataModelingJobsInputs) -> None:
    workflow_id = activity.info().workflow_id
    workflow_run_id = activity.info().workflow_run_id
    assert workflow_id
    assert workflow_run_id
    await _record_skipped_data_modeling_jobs(inputs, workflow_id, workflow_run_id)
