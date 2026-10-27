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
from .notify_materialization_failure import maybe_notify_materialization_failure, notify_node_suspended
from .utils import (
    CONSECUTIVE_FAILURES_TO_SUSPEND,
    bind_data_modeling_log_context,
    maybe_suspend_node_for_engine,
    strip_hostname_from_error,
    update_node_system_properties,
    was_suspended_by_job,
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


def _fail_node(inputs: FailMaterializationInputs, sanitized_error: str) -> Node | None:
    with transaction.atomic():
        node = (
            Node.objects.select_for_update()
            .filter(id=inputs.node_id, team_id=inputs.team_id, dag_id=inputs.dag_id)
            .first()
        )
        if node is None:
            return None
        status = DataModelingJobStatus.CANCELLED if inputs.cancelled else DataModelingJobStatus.FAILED
        update_node_system_properties(
            node,
            status=status,
            job_id=inputs.job_id,
            error=sanitized_error,
        )
        node.save()
    return node


@database_sync_to_async_pool
def _fail_node_and_data_modeling_job(inputs: FailMaterializationInputs):
    # strip hostnames from error for user-facing storage while preserving original for logging
    sanitized_error = strip_hostname_from_error(inputs.error)

    node = _fail_node(inputs, sanitized_error) if inputs.update_node else None

    job = DataModelingJob.objects.get(id=inputs.job_id)

    # if the job is already in a terminal state, don't overwrite it — preserves the first error
    if job.status in (DataModelingJobStatus.FAILED, DataModelingJobStatus.CANCELLED, DataModelingJobStatus.COMPLETED):
        return node, job

    job.status = DataModelingJobStatus.CANCELLED if inputs.cancelled else DataModelingJobStatus.FAILED
    job.rows_materialized = 0
    job.error = sanitized_error
    job.last_run_at = dt.datetime.now(dt.UTC)
    job.save()

    return node, job


@database_sync_to_async_pool
def _get_saved_query_for_job(job: DataModelingJob) -> DataWarehouseSavedQuery | None:
    if not job.saved_query_id:
        return None
    return DataWarehouseSavedQuery.objects.exclude(deleted=True).filter(id=job.saved_query_id).first()


@database_sync_to_async_pool
def _revert_materialization_on_unknown_table(job: DataModelingJob, saved_query: DataWarehouseSavedQuery) -> None:
    saved_query.revert_materialization()
    # we can use this specific language in the error to add these jobs to the daily email digest later
    job.error = (
        f"This materialized view has been reverted to a view because it referenced an unknown table. Error: {job.error}"
    )
    job.save(update_fields=["error"])


@activity.defn
async def fail_materialization_activity(inputs: FailMaterializationInputs) -> str | None:
    """Mark materialization as failed and update node properties.

    Returns the job's run mode, or None when the run failed before choosing one.
    """
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()
    _, job = await _fail_node_and_data_modeling_job(inputs)
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
    # error-specific recovery: revert on unknown table, else suspend the node after repeated failures
    if not inputs.update_node:
        return job.run_mode
    error = inputs.error
    saved_query = None
    suspended = False
    try:
        saved_query = await _get_saved_query_for_job(job)
        if saved_query is None:
            return job.run_mode

        if "Unknown table" in error:
            await logger.ainfo(
                f"Reverting materialization for node {inputs.node_id} due to unknown table reference",
            )
            await _revert_materialization_on_unknown_table(job, saved_query)
        else:
            if await maybe_suspend_node_for_engine(
                node_id=inputs.node_id,
                team_id=inputs.team_id,
                dag_id=inputs.dag_id,
                saved_query_id=saved_query.id,
                engine=DataModelingJobEngine.CLICKHOUSE,
                reason=strip_hostname_from_error(error),
                job_id=inputs.job_id,
            ):
                suspended = True
                get_node_suspended_metric(DataModelingJobEngine.CLICKHOUSE.value).add(1)
                await logger.ainfo(
                    f"Suspended node {inputs.node_id} (clickhouse) after {CONSECUTIVE_FAILURES_TO_SUSPEND} consecutive failures",
                )
            else:
                # A retry after the marker was saved but before anyone was told still owes the notice.
                suspended = await was_suspended_by_job(
                    node_id=inputs.node_id,
                    team_id=inputs.team_id,
                    dag_id=inputs.dag_id,
                    engine=DataModelingJobEngine.CLICKHOUSE,
                    job_id=inputs.job_id,
                )

    except Exception as e:
        capture_exception(e)
        await logger.aexception(
            f"Failed to run error-specific recovery for node {inputs.node_id}: {strip_hostname_from_error(str(e))}"
        )

    # Kept out of the recovery block above: a failing suspend or revert is exactly when someone most
    # needs telling, so it must not take the notification down with it.
    if saved_query is not None and not inputs.cancelled:
        try:
            if suspended:
                # Replaces the failure notification for this run, so nobody gets two for one event.
                await notify_node_suspended(job, saved_query, inputs.team_id, strip_hostname_from_error(error))
                notified = True
            else:
                notified = await maybe_notify_materialization_failure(job, saved_query, inputs.team_id)
            if notified:
                await logger.ainfo(f"Sent materialization failure notification for node {inputs.node_id}")
        except Exception as e:
            capture_exception(e)
            await logger.aexception(
                f"Failed to notify materialization failure for node {inputs.node_id}: {strip_hostname_from_error(str(e))}"
            )
    return job.run_mode
