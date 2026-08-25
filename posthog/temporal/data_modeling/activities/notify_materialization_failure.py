"""Telling people a materialized view broke.

Two shapes, because a failure arrives two ways:

- A view materialized on its own ("Sync now", a single-node schedule) notifies from its own
  failure path, in `maybe_notify_materialization_failure`.
- A view materialized inside a DAG run leaves the in-app notification to the run, which ends by
  posting one notification per audience covering every view it broke. A tier run that breaks many
  views is otherwise that many pings, a few seconds apart.

Email keeps the per-view shape in both cases: it dedupes per (recipient, job) in MessagingRecord,
and the digest already coalesces a day's worth.
"""

import hashlib
import dataclasses

from structlog import get_logger
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User
from posthog.sync import database_sync_to_async_pool
from posthog.tasks.email import send_matview_failure_immediate_email

from products.access_control.backend.facade.user_access_control import UserAccessControl
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
)

from .utils import starts_a_failure_streak, strip_hostname_from_error

LOGGER = get_logger(__name__)

# Beyond this the title's count carries the scale, and the body stays readable.
MAX_NAMED_VIEWS = 5


@dataclasses.dataclass(frozen=True, kw_only=True)
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
    viewers = []
    for user_id, access in accesses:
        try:
            if access.is_organization_admin or access.check_access_level_for_object(
                saved_query, required_level="viewer"
            ):
                viewers.append(user_id)
        except Exception:
            # Dropping only the member whose check failed. Admitting them instead would name a view,
            # its error and its link to someone the same check may be about to deny.
            capture_exception()
    return viewers


class _SavedQueryViewers(RecipientsResolver):
    """Narrow team recipients to the members allowed to open one specific view.

    Both gates run: this one narrows, the shared one in `create_notification` narrows again.
    """

    def __init__(self, saved_query: DataWarehouseSavedQuery) -> None:
        self._saved_query = saved_query

    def resolve(self, target_type: TargetType, target_id: str, team_id: int | None) -> list[int]:
        user_ids = super().resolve(target_type, target_id, team_id)
        if not user_ids:
            return user_ids
        team = Team.objects.filter(id=team_id).first() if team_id is not None else None
        if team is None:
            # No team is no way to run the per-view check, so nobody is told, for the same reason
            # `_viewers_of` drops a member it could not check.
            return []
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
    if not starts_a_failure_streak(saved_query.id, job):
        return False

    # The email task dedupes per (recipient, job) via MessagingRecord, so an activity
    # retry that already sent the in-app notification still can't double-send email.
    send_matview_failure_immediate_email.delay(team_id, str(saved_query.id), str(job.id))

    if job.parent_workflow_id:
        # The DAG run this belongs to notifies for every view it broke, once, at the end.
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


def _dedupe_key(views: list[_FailedView]) -> str:
    """Identity of one notification: this set of failed runs.

    Keyed on the runs rather than the views, so the same views breaking again in a later run notify
    again while a retry of this activity does not. Hashed to fit `idempotency_key`, which a unique
    constraint enforces — the check-then-create it replaces cannot, and this activity does run twice
    when a slow one hits its timeout.
    """
    runs = "|".join(sorted(str(view.job.id) for view in views))
    return f"matview-failure-{hashlib.sha256(runs.encode()).hexdigest()}"


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
        idempotency_key=_dedupe_key(views),
        resolver=resolver,
    )


def _group_by_audience(
    team: Team, views: list[_FailedView], team_user_ids: list[int]
) -> list[tuple[frozenset[int], list[_FailedView]]]:
    """One notification per set of members who can see exactly the same failures.

    Views a member cannot open must not be named to them, so this groups by what each member sees
    rather than by who sees each view. Those are not the same: per-view viewer sets overlap wherever
    one view is denied and another is not — and every org admin sits in all of them — so a member in
    two would get two notifications for one run, each naming part of what broke. Grouping this way,
    every member appears in exactly one group. A team that denies nobody lands in a single group,
    which is the point of coalescing.
    """
    accesses = _access_of(team, team_user_ids)
    visible: dict[int, list[_FailedView]] = {}
    for view in views:
        for user_id in _viewers_of(accesses, view.saved_query):
            visible.setdefault(user_id, []).append(view)

    by_audience: dict[tuple[str, ...], tuple[list[int], list[_FailedView]]] = {}
    for user_id, seen in visible.items():
        # `views` is sorted and iterated in order above, so members seeing the same failures build
        # the same list, and the same key.
        audience, _ = by_audience.setdefault(tuple(str(view.job.id) for view in seen), ([], seen))
        audience.append(user_id)
    return [(frozenset(audience), seen) for audience, seen in by_audience.values()]


@database_sync_to_async_pool
def _notify_dag_materialization_failures(inputs: NotifyDAGMaterializationFailuresInputs) -> int:
    team = Team.objects.filter(id=inputs.team_id).first()
    if team is None:
        return 0

    # A manually triggered run can reuse its workflow id, so matching the parent alone would sweep
    # in an earlier run's failures. Every child of this run ends its id with this run's start time,
    # which the run itself generated — no clock comparison, so no skew to get wrong.
    # `team_id` leads because neither workflow column is indexed, and the suffix match can only ever
    # be a post-filter; it puts the `(team, status)` index in front of a table that only grows.
    failed_jobs = DataModelingJob.objects.filter(
        team_id=inputs.team_id,
        parent_workflow_id=inputs.parent_workflow_id,
        workflow_id__endswith=f"-{inputs.run_started_at}",
        status=DataModelingJobStatus.FAILED,
        engine=DataModelingJobEngine.CLICKHOUSE,
        saved_query__isnull=False,
    ).select_related("saved_query")

    newly_failed = [
        _FailedView(job=job, saved_query=job.saved_query)
        for job in failed_jobs
        if job.saved_query is not None and starts_a_failure_streak(job.saved_query.id, job)
    ]
    if not newly_failed:
        return 0
    # The query above has no order of its own, and a retry has to rebuild the same groups under the
    # same keys to be recognised as one it already sent.
    newly_failed.sort(key=lambda view: str(view.job.id))

    team_user_ids = RecipientsResolver().resolve(TargetType.TEAM, str(inputs.team_id), inputs.team_id)

    sent = 0
    for viewers, views in _group_by_audience(team, newly_failed, team_user_ids):
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
