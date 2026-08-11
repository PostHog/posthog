import datetime as dt
import dataclasses
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction

from structlog import get_logger
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User
from posthog.rbac.user_access_control import UserAccessControl
from posthog.sync import database_sync_to_async_pool
from posthog.tasks.email import send_matview_failure_immediate_email

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
    RecipientsResolver,
    TargetType,
    create_notification,
    has_been_dispatched,
)

from ..metrics import get_node_suspended_metric
from .utils import (
    CONSECUTIVE_FAILURES_TO_SUSPEND,
    bind_data_modeling_log_context,
    maybe_suspend_node_for_engine,
    strip_hostname_from_error,
    update_node_system_properties,
)

if TYPE_CHECKING:
    from django.db.models import QuerySet

LOGGER = get_logger(__name__)

CONSECUTIVE_TIMEOUTS_TO_PAUSE = 5


def _get_previous_jobs(
    saved_query_id: UUID, current_job_id: UUID, count: int, ignore_inconclusive: bool = False
) -> "QuerySet[DataModelingJob]":
    """Get the most recent jobs for a saved query, excluding the current job."""
    jobs = (
        DataModelingJob.objects.filter(saved_query_id=saved_query_id, engine=DataModelingJobEngine.CLICKHOUSE)
        .exclude(id=current_job_id)
        # a skipped run never executed, so it is evidence of neither health nor failure. Leaving it
        # in lets one upstream outage clear a timeout streak that is about to pause the schedule.
        .exclude(status=DataModelingJobStatus.SKIPPED)
    )
    if ignore_inconclusive:
        # Neither status says whether the query recovered: a cancel is our doing (preemption, a
        # deploy), and a run still marked running either is one, or was abandoned by a dead worker.
        # The timeout counter keeps treating both as a break, deliberately.
        jobs = jobs.exclude(status__in=(DataModelingJobStatus.CANCELLED, DataModelingJobStatus.RUNNING))
    return jobs.order_by("-created_at")[:count]


def should_pause_schedule_for_timeout(saved_query_id: UUID, current_job_id: UUID) -> tuple[bool, int]:
    """Check if the schedule should be paused based on consecutive timeout failures.

    Returns True only if all of the previous CONSECUTIVE_TIMEOUTS_TO_PAUSE jobs
    failed due to query timeouts. This prevents pausing schedules for transient
    timeouts that can occur due to temporary ClickHouse load.
    """
    previous_jobs = list(_get_previous_jobs(saved_query_id, current_job_id, CONSECUTIVE_TIMEOUTS_TO_PAUSE))
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
    should_pause, _ = should_pause_schedule_for_timeout(saved_query.id, job.id)
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


class _SavedQueryViewers(RecipientsResolver):
    """Narrow team recipients to the members allowed to open one specific view.

    `create_notification` gates on the parent `warehouse_objects` resource, which cannot see a
    deny placed on an individual view. This repeats the check `Database._is_warehouse_view_denied`
    makes when the same member opens that view, so a notification never names a view they would
    be refused. Both gates run: this one narrows, the shared one narrows again.
    """

    def __init__(self, saved_query: DataWarehouseSavedQuery) -> None:
        self._saved_query = saved_query

    def resolve(self, target_type: TargetType, target_id: str, team_id: int | None) -> list[int]:
        user_ids = super().resolve(target_type, target_id, team_id)
        if not user_ids or team_id is None:
            return user_ids
        team = Team.objects.filter(id=team_id).first()
        if team is None:
            return user_ids

        try:
            return [
                user.id
                for user in User.objects.filter(id__in=user_ids)
                if (access := UserAccessControl(user, team)).is_organization_admin
                or access.check_access_level_for_object(self._saved_query, required_level="viewer")
            ]
        except Exception:
            # Not being able to check must not stop every failure notification.
            capture_exception()
            return user_ids


@database_sync_to_async_pool
def _maybe_notify_materialization_failure(
    job: DataModelingJob, saved_query: DataWarehouseSavedQuery, team_id: int
) -> bool:
    """Notify on the first failure of a streak; repeats of an ongoing streak stay quiet."""
    # An idempotent retry can land here with a job another path already completed or cancelled.
    if job.status != DataModelingJobStatus.FAILED:
        return False
    previous_job = _get_previous_jobs(saved_query.id, job.id, 1, ignore_inconclusive=True).first()
    if previous_job is not None and previous_job.status == DataModelingJobStatus.FAILED:
        return False

    # The email task dedupes per (recipient, job) via MessagingRecord, so an activity
    # retry that already sent the in-app notification still can't double-send email.
    send_matview_failure_immediate_email.delay(team_id, str(saved_query.id), str(job.id))

    if has_been_dispatched(
        notification_type=NotificationType.MATERIALIZATION_FAILURE,
        target_type=TargetType.TEAM,
        target_id=str(team_id),
        resource_id=str(saved_query.id),
        source_id=str(job.id),
    ):
        return False
    create_notification(
        NotificationData(
            team_id=team_id,
            notification_type=NotificationType.MATERIALIZATION_FAILURE,
            priority=Priority.NORMAL,
            title=f"{saved_query.name} failed to materialize"[:255],
            body=strip_hostname_from_error(job.error or "The latest materialization run failed.")[:400],
            target_type=TargetType.TEAM,
            target_id=str(team_id),
            # "warehouse_objects" (not "warehouse_view") is the AC resource — anything else
            # silently skips the access-control filter in create_notification
            resource_type="warehouse_objects",
            resource_id=str(saved_query.id),
            source_url=f"/project/{team_id}/sql?open_view={saved_query.id}",
            source_id=str(job.id),
            resolver=_SavedQueryViewers(saved_query),
        )
    )
    return True


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
            notified = await _maybe_notify_materialization_failure(job, saved_query, inputs.team_id)
            if notified:
                await logger.ainfo(f"Sent materialization failure notification for node {inputs.node_id}")
        except Exception as e:
            capture_exception(e)
            await logger.aexception(
                f"Failed to notify materialization failure for node {inputs.node_id}: {strip_hostname_from_error(str(e))}"
            )
