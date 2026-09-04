import datetime as dt
import dataclasses

from django.db import transaction

from structlog import get_logger
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool

from products.data_modeling.backend.facade.models import (
    DataModelingJob,
    DataModelingJobEngine,
    DataModelingJobStatus,
    DataWarehouseSavedQuery,
    Node,
)

from ..metrics import get_node_suspended_metric
from .notify_materialization_failure import maybe_notify_materialization_failure
from .utils import (
    CONSECUTIVE_FAILURES_TO_SUSPEND,
    bind_data_modeling_log_context,
    has_newer_job,
    has_newer_terminal_job,
    mark_node_suspended,
    maybe_suspend_node_for_engine,
    query_fingerprint,
    strip_hostname_from_error,
    update_node_system_properties,
    update_saved_query_latest_error,
)

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class FailMaterializationInputs:
    team_id: int
    node_id: str
    dag_id: str
    job_id: str
    error: str
    cancelled: bool = False
    update_node: bool = True
    suspend_immediately: bool = False


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class FailNodeAndJobOutcome:
    job: DataModelingJob
    is_latest_terminal: bool
    suspended_immediately: bool


@database_sync_to_async_pool
def _fail_node_and_data_modeling_job(inputs: FailMaterializationInputs) -> FailNodeAndJobOutcome:
    sanitized_error = strip_hostname_from_error(inputs.error)

    with transaction.atomic():
        job = DataModelingJob.objects.select_for_update().get(id=inputs.job_id)
        if job.status in (
            DataModelingJobStatus.FAILED,
            DataModelingJobStatus.CANCELLED,
            DataModelingJobStatus.COMPLETED,
        ):
            return FailNodeAndJobOutcome(
                job=job,
                is_latest_terminal=not has_newer_terminal_job(job),
                suspended_immediately=False,
            )

        node = None
        suspended_immediately = False
        is_latest_terminal = not has_newer_terminal_job(job)
        if inputs.update_node:
            locked_node = Node.objects.select_for_update().get(
                id=inputs.node_id, team_id=inputs.team_id, dag_id=inputs.dag_id
            )
            is_latest_terminal = not has_newer_terminal_job(job)
            if is_latest_terminal:
                node = locked_node
                update_node_system_properties(
                    node,
                    status=DataModelingJobStatus.CANCELLED if inputs.cancelled else DataModelingJobStatus.FAILED,
                    job_id=inputs.job_id,
                    error=sanitized_error,
                )
            if node is not None and inputs.suspend_immediately and node.saved_query_id is not None:
                fingerprint = query_fingerprint(
                    DataWarehouseSavedQuery.objects.filter(id=node.saved_query_id)
                    .values_list("query", flat=True)
                    .first()
                )
                mark_node_suspended(
                    node,
                    engine=DataModelingJobEngine.CLICKHOUSE,
                    reason=sanitized_error,
                    job_id=inputs.job_id,
                    fingerprint=fingerprint,
                    enforce_without_flag=True,
                )
                suspended_immediately = True
            if node is not None:
                node.save()

        job.status = DataModelingJobStatus.CANCELLED if inputs.cancelled else DataModelingJobStatus.FAILED
        job.rows_materialized = 0
        job.error = sanitized_error
        job.last_run_at = dt.datetime.now(dt.UTC)
        job.save()

    return FailNodeAndJobOutcome(
        job=job,
        is_latest_terminal=is_latest_terminal,
        suspended_immediately=suspended_immediately,
    )


@database_sync_to_async_pool
def _get_saved_query_for_job(job: DataModelingJob) -> DataWarehouseSavedQuery | None:
    if not job.saved_query_id:
        return None
    return DataWarehouseSavedQuery.objects.exclude(deleted=True).filter(id=job.saved_query_id).first()


@database_sync_to_async_pool
def _revert_materialization_on_unknown_table(job: DataModelingJob, saved_query: DataWarehouseSavedQuery) -> bool:
    if has_newer_job(job):
        return False
    saved_query.revert_materialization()
    # we can use this specific language in the error to add these jobs to the daily email digest later
    job.error = (
        f"This materialized view has been reverted to a view because it referenced an unknown table. Error: {job.error}"
    )
    job.save(update_fields=["error"])
    return True


@activity.defn
async def fail_materialization_activity(inputs: FailMaterializationInputs) -> None:
    """Mark materialization as failed and update node properties."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()
    outcome = await _fail_node_and_data_modeling_job(inputs)
    job = outcome.job
    if job.saved_query_id is not None:
        bind_data_modeling_log_context(inputs.team_id, job.saved_query_id)
    job_context = (
        f"node={inputs.node_id} dag={inputs.dag_id} job={job.id} "
        f"workflow={job.workflow_id} workflow_run={job.workflow_run_id}"
    )
    # The bound context above puts this line in front of users, so it carries the same sanitized
    # error the job row does. The raw one stays write-only, where only internal logging sees it.
    await logger.aerror(f"Failed materialization job: {job_context} error={strip_hostname_from_error(inputs.error)}")
    await logger.aerror(f"Failed materialization job: {job_context} error={inputs.error}", write_only=True)
    error = inputs.error
    saved_query = await _get_saved_query_for_job(job) if inputs.update_node else None
    if saved_query is not None and outcome.is_latest_terminal:
        try:
            if outcome.suspended_immediately:
                get_node_suspended_metric(DataModelingJobEngine.CLICKHOUSE.value).add(1)
                await logger.ainfo(f"Suspended node {inputs.node_id} (clickhouse) immediately")
            elif "Unknown table" in error:
                if await _revert_materialization_on_unknown_table(job, saved_query):
                    await logger.ainfo(
                        f"Reverted materialization for node {inputs.node_id} due to unknown table reference",
                    )
            else:
                suspended = await maybe_suspend_node_for_engine(
                    node_id=inputs.node_id,
                    team_id=inputs.team_id,
                    dag_id=inputs.dag_id,
                    saved_query_id=saved_query.id,
                    engine=DataModelingJobEngine.CLICKHOUSE,
                    reason=strip_hostname_from_error(error),
                    job_id=inputs.job_id,
                )
                if suspended:
                    get_node_suspended_metric(DataModelingJobEngine.CLICKHOUSE.value).add(1)
                    await logger.ainfo(
                        f"Suspended node {inputs.node_id} (clickhouse) after "
                        f"{CONSECUTIVE_FAILURES_TO_SUSPEND} consecutive failures",
                    )

        except Exception as e:
            capture_exception(e)
            await logger.aexception(
                f"Failed to run error-specific recovery for node {inputs.node_id}: {strip_hostname_from_error(str(e))}"
            )

    await update_saved_query_latest_error(job.id)

    # Keep notification outside recovery so a failed revert or suspension does not suppress it.
    if saved_query is not None and outcome.is_latest_terminal and not inputs.cancelled:
        try:
            notified = await maybe_notify_materialization_failure(job, saved_query, inputs.team_id)
            if notified:
                await logger.ainfo(f"Sent materialization failure notification for node {inputs.node_id}")
        except Exception as e:
            capture_exception(e)
            await logger.aexception(
                f"Failed to notify materialization failure for node {inputs.node_id}: {strip_hostname_from_error(str(e))}"
            )
