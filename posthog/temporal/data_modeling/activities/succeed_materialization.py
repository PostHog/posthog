import datetime as dt
import dataclasses

from django.db import transaction

from celery import current_app
from structlog import get_logger
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool

from products.data_modeling.backend.facade.models import (
    DataModelingJob,
    DataModelingJobEngine,
    DataModelingJobStatus,
    Node,
)

from .utils import clear_node_suspension, update_node_system_properties

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class SucceedMaterializationInputs:
    team_id: int
    node_id: str
    dag_id: str
    job_id: str
    row_count: int
    duration_seconds: float
    update_node: bool = True


@dataclasses.dataclass
class SucceedMaterializationResult:
    """Enough for the workflow to fire the semantic-enrichment child only when the view actually changed."""

    enrichment_needed: bool = False
    saved_query_id: str | None = None


def _view_enrichment_needed(node: Node | None) -> tuple[bool, str | None]:
    """Whether the view's descriptions are stale vs the just-materialized state.

    Compares the current enrichment hash to the one stored on the saved query so a steady-state
    (hourly) re-materialization doesn't spawn a no-op enrichment child every run. Best-effort — any
    failure degrades to "not needed" and never fails the materialization.
    """
    if node is None or node.saved_query_id is None:
        return False, None
    try:
        from products.data_modeling.backend.facade.api import (  # noqa: PLC0415
            compute_enrichment_hash,
            enrichment_gates_pass,
        )

        saved_query = node.saved_query
        if saved_query is None:
            return False, str(node.saved_query_id)
        if compute_enrichment_hash(saved_query) == saved_query.semantic_enrichment_hash:
            return False, str(node.saved_query_id)
        # Gate on AI-processing approval before enqueuing, so a non-consented team's re-materialization
        # never creates enrichment workflow work. The child activity re-checks it as the source of truth.
        if not enrichment_gates_pass(saved_query):
            return False, str(node.saved_query_id)
        return True, str(node.saved_query_id)
    except Exception as e:
        capture_exception(e)
        return False, str(node.saved_query_id)


@database_sync_to_async_pool
def _succeed_node_and_data_modeling_job(
    inputs: SucceedMaterializationInputs,
) -> tuple[Node | None, DataModelingJob, bool, str | None]:
    node: Node | None = None
    if inputs.update_node:
        with transaction.atomic():
            # of=("self",) + select_related: skip the extra node.saved_query query without locking the joined row.
            node = (
                Node.objects.select_for_update(of=("self",))
                .select_related("saved_query")
                .get(id=inputs.node_id, team_id=inputs.team_id, dag_id=inputs.dag_id)
            )
            status = DataModelingJobStatus.COMPLETED
            update_node_system_properties(
                node,
                status=status,
                job_id=inputs.job_id,
                rows=inputs.row_count,
                duration_seconds=inputs.duration_seconds,
            )
            clear_node_suspension(node, engine=DataModelingJobEngine.CLICKHOUSE)
            node.save()

    enrichment_needed, enrichment_saved_query_id = _view_enrichment_needed(node)

    job = DataModelingJob.objects.get(id=inputs.job_id)

    # if the job is already in a terminal state, don't overwrite it
    if job.status in (DataModelingJobStatus.FAILED, DataModelingJobStatus.CANCELLED, DataModelingJobStatus.COMPLETED):
        return node, job, enrichment_needed, enrichment_saved_query_id

    job.status = DataModelingJobStatus.COMPLETED
    job.rows_materialized = inputs.row_count
    job.last_run_at = dt.datetime.now(dt.UTC)
    job.error = None
    job.save()

    if node is not None and node.saved_query_id is not None:
        saved_query_id = str(node.saved_query_id)
        team_id = inputs.team_id
        transaction.on_commit(lambda: _enqueue_custom_property_sync(team_id, saved_query_id))
    return node, job, enrichment_needed, enrichment_saved_query_id


def _enqueue_custom_property_sync(team_id: int, saved_query_id: str) -> None:
    try:
        current_app.send_task(
            "customer_analytics.process_custom_property_sync",
            kwargs={"team_id": team_id, "saved_query_id": saved_query_id},
        )
    except Exception as e:
        LOGGER.exception("custom_property_sync_enqueue_failed", team_id=team_id, saved_query_id=saved_query_id)
        capture_exception(e)


@activity.defn
async def succeed_materialization_activity(inputs: SucceedMaterializationInputs) -> SucceedMaterializationResult:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    node, job, enrichment_needed, saved_query_id = await _succeed_node_and_data_modeling_job(inputs)

    await logger.ainfo(
        f"Succeeded materialization job: node={inputs.node_id} dag={inputs.dag_id} job={job.id} "
        f"workflow={job.workflow_id} workflow_run={job.workflow_run_id}"
    )
    return SucceedMaterializationResult(enrichment_needed=enrichment_needed, saved_query_id=saved_query_id)
