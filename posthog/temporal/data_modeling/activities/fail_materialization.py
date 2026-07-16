import dataclasses
from typing import TYPE_CHECKING
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
from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    TargetType,
    create_notification,
)

from ..metrics import get_node_suspended_metric
from .utils import (
    CONSECUTIVE_FAILURES_TO_SUSPEND,
    maybe_suspend_node_for_engine,
    strip_hostname_from_error,
    update_node_system_properties,
)

if TYPE_CHECKING:
    from django.db.models import QuerySet

LOGGER = get_logger(__name__)

CONSECUTIVE_RESOURCE_LIMIT_FAILURES_TO_PAUSE = 5
CONSECUTIVE_TIMEOUTS_TO_PAUSE = CONSECUTIVE_RESOURCE_LIMIT_FAILURES_TO_PAUSE
RESOURCE_LIMIT_ERROR_MARKERS = (
    "TOO_MANY_BYTES",
    "too many bytes",
    "MEMORY_LIMIT_EXCEEDED",
    "Memory limit exceeded",
    "Timeout exceeded",
    "exceeded timeout",
)


def _get_previous_jobs(saved_query_id: UUID, current_job_id: UUID, count: int) -> "QuerySet[DataModelingJob]":
    """Get the most recent jobs for a saved query, excluding the current job."""
    return (
        DataModelingJob.objects.filter(saved_query_id=saved_query_id, engine=DataModelingJobEngine.CLICKHOUSE)
        .exclude(id=current_job_id)
        .order_by("-created_at")[:count]
    )


def is_resource_limit_error(error: str | None) -> bool:
    if not error:
        return False
    return any(marker.lower() in error.lower() for marker in RESOURCE_LIMIT_ERROR_MARKERS)


def should_pause_schedule_for_resource_limit(
    saved_query_id: UUID, current_job_id: UUID, current_error: str | None
) -> tuple[bool, int]:
    """Check if the schedule should be paused after consecutive resource-limit failures.

    The current failure counts toward the threshold. Successful jobs and failures for other
    reasons reset the consecutive count.
    """
    if not is_resource_limit_error(current_error):
        return False, 0

    previous_jobs = list(
        _get_previous_jobs(saved_query_id, current_job_id, CONSECUTIVE_RESOURCE_LIMIT_FAILURES_TO_PAUSE - 1)
    )
    count = 1
    for job in previous_jobs:
        if job.status != DataModelingJobStatus.FAILED:
            break
        if not is_resource_limit_error(job.error):
            break
        count += 1
    return count >= CONSECUTIVE_RESOURCE_LIMIT_FAILURES_TO_PAUSE, count


def should_pause_schedule_for_timeout(saved_query_id: UUID, current_job_id: UUID) -> tuple[bool, int]:
    return should_pause_schedule_for_resource_limit(saved_query_id, current_job_id, "Timeout exceeded")


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
    job.save()

    return node, job


@database_sync_to_async_pool
def _get_saved_query_for_job(job: DataModelingJob) -> DataWarehouseSavedQuery | None:
    if not job.saved_query_id:
        return None
    return DataWarehouseSavedQuery.objects.exclude(deleted=True).filter(id=job.saved_query_id).first()


def _notify_owner_schedule_paused(saved_query: DataWarehouseSavedQuery, error: str) -> None:
    target_type = TargetType.USER if saved_query.created_by_id else TargetType.TEAM
    target_id = str(saved_query.created_by_id or saved_query.team_id)
    create_notification(
        NotificationData(
            team_id=saved_query.team_id,
            notification_type=NotificationType.PIPELINE_FAILURE,
            priority=Priority.NORMAL,
            title="Model refresh schedule paused",
            body=(
                f'PostHog paused scheduled refreshes for "{saved_query.name}" after '
                f"{CONSECUTIVE_RESOURCE_LIMIT_FAILURES_TO_PAUSE} failures because the query exceeded processing limits. "
                f"Review the model query, reduce the data it scans, then reset its schedule. "
                f"Latest error: {error[:500]}"
            ),
            target_type=target_type,
            target_id=target_id,
            resource_id=str(saved_query.id),
            source_url="/models",
        )
    )


@database_sync_to_async_pool
def _maybe_pause_schedule_on_resource_limit(job: DataModelingJob, saved_query: DataWarehouseSavedQuery) -> bool:
    """Pause the schedule after repeated resource-limit failures and notify the owner.

    Returns True if the schedule was paused, False otherwise.
    """
    should_pause, _ = should_pause_schedule_for_resource_limit(saved_query.id, job.id, job.error)
    if not should_pause:
        return False

    saved_query.sync_frequency_interval = None
    saved_query.save(update_fields=["sync_frequency_interval"])
    pause_saved_query_schedule(saved_query)
    original_error = job.error or "Unknown resource-limit error"
    job.error = (
        "This materialized view sync schedule has been paused after the query repeatedly exceeded processing limits. "
        f"Modify the query to reduce the data it scans, then reset the sync schedule. Error: {original_error}"
    )
    job.save(update_fields=["error"])
    try:
        _notify_owner_schedule_paused(saved_query, original_error)
    except Exception:
        LOGGER.warning(
            "materialization_schedule_paused_notification_failed",
            saved_query_id=str(saved_query.id),
            team_id=saved_query.team_id,
            exc_info=True,
        )
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
    await logger.aerror(
        f"Failed materialization job: node={inputs.node_id} dag={inputs.dag_id} job={job.id} "
        f"workflow={job.workflow_id} workflow_run={job.workflow_run_id} error={inputs.error}"
    )
    # error-specific recovery: pause on resource limits, revert on unknown table, else suspend after repeated failures
    if not inputs.update_node:
        return
    error = inputs.error
    try:
        saved_query = await _get_saved_query_for_job(job)
        if saved_query is None:
            return

        if is_resource_limit_error(error):
            paused = await _maybe_pause_schedule_on_resource_limit(job, saved_query)
            if paused:
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
                    f"Pausing schedule and suspending node {inputs.node_id} due to "
                    f"{CONSECUTIVE_RESOURCE_LIMIT_FAILURES_TO_PAUSE} consecutive resource-limit failures",
                )
            else:
                await logger.ainfo(
                    f"Resource-limit failure for node {inputs.node_id} - not pausing schedule "
                    f"(fewer than {CONSECUTIVE_RESOURCE_LIMIT_FAILURES_TO_PAUSE} consecutive failures)",
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
        await logger.aexception(f"Failed to run error-specific recovery for node {inputs.node_id}: {str(e)}")
