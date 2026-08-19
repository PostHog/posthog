import datetime as dt
import dataclasses
from uuid import UUID

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
from products.data_warehouse.backend.facade.api import pause_saved_query_schedule

from ..metrics import get_node_suspended_metric
from .notify_materialization_failure import maybe_notify_materialization_failure
from .utils import (
    CONSECUTIVE_FAILURES_TO_SUSPEND,
    bind_data_modeling_log_context,
    get_previous_jobs,
    maybe_suspend_node_for_engine,
    strip_hostname_from_error,
    update_node_system_properties,
)

LOGGER = get_logger(__name__)

CONSECUTIVE_TIMEOUTS_TO_PAUSE = 5


def should_pause_schedule_for_timeout(saved_query_id: UUID, current_job: DataModelingJob) -> tuple[bool, int]:
    """Check if the schedule should be paused based on consecutive timeout failures.

    Returns True only if all of the previous CONSECUTIVE_TIMEOUTS_TO_PAUSE jobs
    failed due to query timeouts. This prevents pausing schedules for transient
    timeouts that can occur due to temporary ClickHouse load.
    """
    previous_jobs = list(get_previous_jobs(saved_query_id, current_job, CONSECUTIVE_TIMEOUTS_TO_PAUSE))
    count = 0
    for job in previous_jobs:
        if job.status != DataModelingJobStatus.FAILED:
            break
        if not job.error or ("Timeout exceeded" not in job.error and "exceeded timeout" not in job.error.lower()):
            break
        count += 1
    return count == CONSECUTIVE_TIMEOUTS_TO_PAUSE, count


@dataclasses.dataclass
class FailMaterializationInputs:
    team_id: int
    node_id: str
    dag_id: str
    job_id: str
    error: str
    cancelled: bool = False
    update_node: bool = True


@database_sync_to_async_pool
def _fail_node_and_data_modeling_job(inputs: FailMaterializationInputs):
    # strip hostnames from error for user-facing storage while preserving original for logging
    sanitized_error = strip_hostname_from_error(inputs.error)

    node = None
    if inputs.update_node:
        with transaction.atomic():
            node = Node.objects.select_for_update().get(id=inputs.node_id, team_id=inputs.team_id, dag_id=inputs.dag_id)
            status = DataModelingJobStatus.CANCELLED if inputs.cancelled else DataModelingJobStatus.FAILED
            update_node_system_properties(
                node,
                status=status,
                job_id=inputs.job_id,
                error=sanitized_error,
            )
            node.save()

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
def _maybe_pause_schedule_on_timeout(job: DataModelingJob, saved_query: DataWarehouseSavedQuery) -> bool:
    """Pause the schedule only if the previous N jobs all failed due to timeouts.

    Returns True if the schedule was paused, False otherwise. This prevents pausing
    schedules for transient timeouts that can occur due to temporary ClickHouse load.
    """
    should_pause, _ = should_pause_schedule_for_timeout(saved_query.id, job)
    if not should_pause:
        return False

    saved_query.sync_frequency_interval = None
    saved_query.save(update_fields=["sync_frequency_interval"])
    pause_saved_query_schedule(saved_query)
    job.error = f"This materialized view sync schedule has been paused until you modify the query and reset the sync schedule. Error: {job.error}"
    job.save(update_fields=["error"])
    return True


@database_sync_to_async_pool
def _revert_materialization_on_unknown_table(job: DataModelingJob, saved_query: DataWarehouseSavedQuery) -> None:
    saved_query.revert_materialization()
    # we can use this specific language in the error to add these jobs to the daily email digest later
    job.error = (
        f"This materialized view has been reverted to a view because it referenced an unknown table. Error: {job.error}"
    )
    job.save(update_fields=["error"])


@activity.defn
async def fail_materialization_activity(inputs: FailMaterializationInputs) -> None:
    """Mark materialization as failed and update node properties."""
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
    # error-specific recovery: pause schedule on timeout, revert on unknown table, else suspend after repeated failures
    if not inputs.update_node:
        return
    error = inputs.error
    saved_query = None
    try:
        saved_query = await _get_saved_query_for_job(job)
        if saved_query is None:
            return

        if "Timeout exceeded" in error:
            paused = await _maybe_pause_schedule_on_timeout(job, saved_query)
            if paused:
                await logger.ainfo(
                    f"Pausing schedule for node {inputs.node_id} due to {CONSECUTIVE_TIMEOUTS_TO_PAUSE} consecutive timeout failures",
                )
            else:
                await logger.ainfo(
                    f"Timeout for node {inputs.node_id} - not pausing schedule (fewer than {CONSECUTIVE_TIMEOUTS_TO_PAUSE} consecutive timeouts)",
                )
        elif "Unknown table" in error:
            await logger.ainfo(
                f"Reverting materialization for node {inputs.node_id} due to unknown table reference",
            )
            await _revert_materialization_on_unknown_table(job, saved_query)
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
                    f"Suspended node {inputs.node_id} (clickhouse) after {CONSECUTIVE_FAILURES_TO_SUSPEND} consecutive failures",
                )

    except Exception as e:
        capture_exception(e)
        await logger.aexception(
            f"Failed to run error-specific recovery for node {inputs.node_id}: {strip_hostname_from_error(str(e))}"
        )

    # Kept out of the recovery block above: a failing pause or revert is exactly when someone most
    # needs telling, so it must not take the notification down with it.
    if saved_query is not None and not inputs.cancelled:
        try:
            notified = await maybe_notify_materialization_failure(job, saved_query, inputs.team_id)
            if notified:
                await logger.ainfo(f"Sent materialization failure notification for node {inputs.node_id}")
        except Exception as e:
            capture_exception(e)
            await logger.aexception(
                f"Failed to notify materialization failure for node {inputs.node_id}: {strip_hostname_from_error(str(e))}"
            )
