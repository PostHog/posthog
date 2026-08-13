"""Telling people a materialized view broke.

Two shapes, because a failure arrives two ways:

- A view materialized on its own ("Sync now", a single-node schedule) notifies from its own
  failure path, in `maybe_notify_materialization_failure`.
- A view materialized inside a DAG run leaves the in-app notification to the run, which ends by
  posting one notification per audience covering every view it broke. A tier run that breaks 42
  views is 42 pings a few seconds apart otherwise.

Email keeps the per-view shape in both cases: it dedupes per (recipient, job) in MessagingRecord,
and the digest already coalesces a day's worth.
"""

import dataclasses

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
)
from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    RecipientsResolver,
    TargetType,
    create_notification,
    has_been_dispatched,
)

from .utils import starts_a_failure_streak, strip_hostname_from_error

LOGGER = get_logger(__name__)

# Beyond this the title's count carries the scale, and the body stays readable.
MAX_NAMED_VIEWS = 5


@dataclasses.dataclass
class NotifyDAGMaterializationFailuresInputs:
    team_id: int
    dag_id: str
    parent_workflow_id: str
    # `start_time.isoformat()`, the same value the run put at the end of each child's workflow id.
    run_started_at: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class _FailedView:
    """A failed job with the view it was materializing.

    `DataModelingJob.saved_query` is nullable, and everything below needs both halves. Pairing them
    once, where the query already excluded the null ones, keeps the rest free of the impossible case.
    """

    job: DataModelingJob
    saved_query: DataWarehouseSavedQuery


def _access_of(team: Team, user_ids: list[int]) -> list[tuple[int, UserAccessControl]]:
    """Build each member's access once, so a run that broke many views doesn't rebuild it per view."""
    return [(user.id, UserAccessControl(user, team)) for user in User.objects.filter(id__in=user_ids)]


def _viewers_of(accesses: list[tuple[int, UserAccessControl]], saved_query: DataWarehouseSavedQuery) -> list[int]:
    """Keep only the members allowed to open one specific view.

    `create_notification` gates on the parent `warehouse_objects` resource, which cannot see a
    deny placed on an individual view. This repeats the check `Database._is_warehouse_view_denied`
    makes when the same member opens that view, so a notification never names a view they would
    be refused.
    """
    try:
        return [
            user_id
            for user_id, access in accesses
            if access.is_organization_admin
            or access.check_access_level_for_object(saved_query, required_level="viewer")
        ]
    except Exception:
        # Not being able to check must not stop every failure notification.
        capture_exception()
        return [user_id for user_id, _ in accesses]


class _SavedQueryViewers(RecipientsResolver):
    """Narrow team recipients to the members allowed to open one specific view.

    Both gates run: this one narrows, the shared one in `create_notification` narrows again.
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
        return _viewers_of(_access_of(team, user_ids), self._saved_query)


class _PrecomputedViewers(RecipientsResolver):
    """Recipients the coalescing activity already narrowed, per view, before grouping."""

    def __init__(self, allowed: frozenset[int]) -> None:
        self._allowed = allowed

    def resolve(self, target_type: TargetType, target_id: str, team_id: int | None) -> list[int]:
        return [user_id for user_id in super().resolve(target_type, target_id, team_id) if user_id in self._allowed]


@database_sync_to_async_pool
def maybe_notify_materialization_failure(
    job: DataModelingJob, saved_query: DataWarehouseSavedQuery, team_id: int
) -> bool:
    """Notify on the first failure of a streak; repeats of an ongoing streak stay quiet."""
    # An idempotent retry can land here with a job another path already completed or cancelled.
    if job.status != DataModelingJobStatus.FAILED:
        return False
    if not starts_a_failure_streak(saved_query.id, job.id):
        return False

    # The email task dedupes per (recipient, job) via MessagingRecord, so an activity
    # retry that already sent the in-app notification still can't double-send email.
    send_matview_failure_immediate_email.delay(team_id, str(saved_query.id), str(job.id))

    if job.parent_workflow_id:
        # The DAG run this belongs to notifies for every view it broke, once, at the end.
        return False

    if has_been_dispatched(
        notification_type=NotificationType.MATERIALIZATION_FAILURE,
        target_type=TargetType.TEAM,
        target_id=str(team_id),
        resource_id=str(saved_query.id),
        source_id=str(job.id),
    ):
        return False
    create_notification(
        _failure_notification(
            team_id=team_id,
            views=[_FailedView(job=job, saved_query=saved_query)],
            resolver=_SavedQueryViewers(saved_query),
            source_id=str(job.id),
        )
    )
    return True


def _failure_copy(views: list[_FailedView]) -> tuple[str, str]:
    names = [view.saved_query.name for view in views]
    if len(names) == 1:
        return (
            f"{names[0]} failed to materialize",
            strip_hostname_from_error(views[0].job.error or "The latest materialization run failed."),
        )
    body = ", ".join(names[:MAX_NAMED_VIEWS])
    if len(names) > MAX_NAMED_VIEWS:
        body = f"{body}, and {len(names) - MAX_NAMED_VIEWS} more"
    return f"{len(names)} views failed to materialize", body


def _failure_notification(
    *, team_id: int, views: list[_FailedView], resolver: RecipientsResolver, source_id: str
) -> NotificationData:
    title, body = _failure_copy(views)
    source_url = f"/project/{team_id}/sql"
    if len(views) == 1:
        source_url = f"{source_url}?open_view={views[0].saved_query.id}"
    return NotificationData(
        team_id=team_id,
        notification_type=NotificationType.MATERIALIZATION_FAILURE,
        priority=Priority.NORMAL,
        title=title[:255],
        body=body[:400],
        target_type=TargetType.TEAM,
        target_id=str(team_id),
        # "warehouse_objects" (not "warehouse_view") is the AC resource — anything else
        # silently skips the access-control filter in create_notification
        resource_type="warehouse_objects",
        resource_id=str(views[0].saved_query.id),
        source_url=source_url,
        source_id=source_id,
        resolver=resolver,
    )


def _group_by_audience(
    team: Team, views: list[_FailedView], team_user_ids: list[int]
) -> dict[frozenset[int], list[_FailedView]]:
    """Views a member cannot open must not be named to them, so group by who may see them.

    A team that denies nobody lands in a single group, which is the point of coalescing.
    """
    accesses = _access_of(team, team_user_ids)
    by_audience: dict[frozenset[int], list[_FailedView]] = {}
    for view in views:
        viewers = frozenset(_viewers_of(accesses, view.saved_query))
        if viewers:
            by_audience.setdefault(viewers, []).append(view)
    return by_audience


@database_sync_to_async_pool
def _notify_dag_materialization_failures(inputs: NotifyDAGMaterializationFailuresInputs) -> int:
    team = Team.objects.filter(id=inputs.team_id).first()
    if team is None:
        return 0

    # A manually triggered run can reuse its workflow id, so matching the parent alone would sweep
    # in an earlier run's failures. Every child of this run ends its id with this run's start time,
    # which the run itself generated — no clock comparison, so no skew to get wrong.
    failed_jobs = DataModelingJob.objects.filter(
        parent_workflow_id=inputs.parent_workflow_id,
        workflow_id__endswith=f"-{inputs.run_started_at}",
        status=DataModelingJobStatus.FAILED,
        engine=DataModelingJobEngine.CLICKHOUSE,
        saved_query__isnull=False,
    ).select_related("saved_query")

    newly_failed = [
        _FailedView(job=job, saved_query=job.saved_query)
        for job in failed_jobs
        if job.saved_query is not None and starts_a_failure_streak(job.saved_query.id, job.id)
    ]
    if not newly_failed:
        return 0

    team_user_ids = RecipientsResolver().resolve(TargetType.TEAM, str(inputs.team_id), inputs.team_id)

    sent = 0
    for viewers, views in _group_by_audience(team, newly_failed, team_user_ids).items():
        # Sorted, so a retry of this activity rebuilds the same key and skips what it already sent.
        # The key is the group's first job rather than the run, both to stay inside `source_id`'s 64
        # characters and so a view that recovers and breaks again under one workflow id notifies twice.
        views.sort(key=lambda view: str(view.saved_query.id))
        if has_been_dispatched(
            notification_type=NotificationType.MATERIALIZATION_FAILURE,
            target_type=TargetType.TEAM,
            target_id=str(inputs.team_id),
            resource_id=str(views[0].saved_query.id),
            source_id=str(views[0].job.id),
        ):
            continue
        create_notification(
            _failure_notification(
                team_id=inputs.team_id,
                views=views,
                resolver=_PrecomputedViewers(viewers),
                source_id=str(views[0].job.id),
            )
        )
        sent += 1
    return sent


@activity.defn
async def notify_dag_materialization_failures_activity(inputs: NotifyDAGMaterializationFailuresInputs) -> int:
    """Post one notification per audience covering every view this DAG run broke."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()
    try:
        sent = await _notify_dag_materialization_failures(inputs)
    except Exception as e:
        capture_exception(e)
        await logger.aexception(
            f"Failed to notify materialization failures for dag {inputs.dag_id}: {strip_hostname_from_error(str(e))}"
        )
        return 0
    if sent:
        await logger.ainfo(f"Sent {sent} coalesced materialization failure notification(s) for dag {inputs.dag_id}")
    return sent
