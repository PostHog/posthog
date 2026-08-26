"""Tell the team when a model starts failing its checks.

Only the pass-to-fail edge notifies, and only for error-severity checks. A check that keeps failing
run after run is already known about; re-notifying every run is how an inbox gets ignored.
"""

from typing import cast

import structlog

from posthog.models import Team, User
from posthog.scopes import APIScopeObject

from products.access_control.backend.facade.user_access_control import (
    UserAccessControl,
    access_level_satisfied_for_resource,
)
from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    RecipientsResolver,
    TargetType,
    create_notification,
)

from ..facade.enums import CheckRunStatus, SubjectType
from ..models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun
from .checks import checks_for_subject
from .flags import is_data_quality_checks_enabled_for_team_id
from .subject_access import denied_subject_names, is_subject_denied, referenced_subject_names, referencing_check_types

LOGGER = structlog.get_logger(__name__)

# Object-level access controls for a warehouse table or view are keyed on the child resource; both
# inherit from the `warehouse_objects` umbrella the built-in resource-level filter checks.
_SUBJECT_RESOURCE: dict[SubjectType, APIScopeObject] = {
    SubjectType.TABLE: cast(APIScopeObject, "warehouse_table"),
    SubjectType.VIEW: cast(APIScopeObject, "warehouse_view"),
}


class _WarehouseSubjectResolver(RecipientsResolver):
    """Drop members who must not receive this check's warehouse metadata or its failing-row count.

    Three gates on top of the built-in resource-level `warehouse_objects` filter that
    `create_notification` runs:

    - **Object-level** access to *this* table or view. The resource-level filter only asks whether a
      member can see warehouse objects at all, so a member with general warehouse access but an
      explicit denial on the subject would still receive its name, column, check type, and count.
    - **Referenced-subject** access. A `relationships` check reads a second subject and a `custom_sql`
      check reads arbitrary tables, so a failure count is an oracle over those too. A member denied
      any of the names passed in must be dropped, matching how the run-history API gates them.
    - **Query** viewer access. The body's `failed_row_count` is a count oracle over the underlying
      warehouse rows that the run-history API gates behind query access, so a member denied `query`
      must not read it from the notification either.
    """

    def __init__(
        self,
        team: Team,
        subject_type: str,
        subject_uuid: str,
        referenced_names: list[str] | None = None,
    ) -> None:
        self._team = team
        self._subject_type = subject_type
        self._subject_uuid = subject_uuid
        self._referenced_names = referenced_names or []
        # One access-control object per member, reused across both gates below (and the warehouse
        # database build the referenced-subject gate runs) so a single failing check doesn't rebuild
        # it -- and its membership, role, and access-control lookups -- once per pass.
        self._access: dict[int, UserAccessControl] = {}

    def _access_of(self, user: User) -> UserAccessControl:
        access = self._access.get(user.id)
        if access is None:
            access = UserAccessControl(user, self._team)
            self._access[user.id] = access
        return access

    def _access_controls_supported(self, user_ids: list[int]) -> bool:
        # When access controls aren't available for the org, the built-in filter lets everyone
        # through and neither gate below can deny anyone; the callers skip their per-member work.
        sample = User.objects.filter(id__in=user_ids).first()
        return sample is not None and self._access_of(sample).access_controls_supported

    def resolve(self, target_type: TargetType, target_id: str, team_id: int | None) -> list[int]:
        user_ids = super().resolve(target_type, target_id, team_id)
        user_ids = self.filter_by_access_control(user_ids, "query", self._team)
        user_ids = self._filter_by_object_access(user_ids)
        return self._filter_by_referenced_subject_access(user_ids)

    def _filter_by_object_access(self, user_ids: list[int]) -> list[int]:
        resource = _SUBJECT_RESOURCE.get(SubjectType(self._subject_type))
        if resource is None:
            return user_ids
        object_id = self._subject_uuid

        if not self._access_controls_supported(user_ids):
            return user_ids

        allowed: list[int] = []
        for user in User.objects.filter(id__in=user_ids):
            level = self._access_of(user).bulk_object_access_levels(resource, [(object_id, None)]).get(object_id)
            if level is not None and access_level_satisfied_for_resource(resource, level, "viewer"):
                allowed.append(user.id)
        return allowed

    def _filter_by_referenced_subject_access(self, user_ids: list[int]) -> list[int]:
        # The declared subject isn't the only one the count depends on: a relationships check reads
        # its target and a custom_sql check reads arbitrary tables. Drop members denied any of those,
        # matching the run-history endpoint -- resolved by name the same way the loaders resolve them.
        if not self._referenced_names:
            return user_ids

        # No warehouse access control means no denials, so skip the per-member database build the
        # denial check would otherwise run -- the same early exit the object-access gate makes.
        if not self._access_controls_supported(user_ids):
            return user_ids

        allowed: list[int] = []
        for user in User.objects.filter(id__in=user_ids):
            denied = denied_subject_names(self._team, user, self._access_of(user))
            if not any(is_subject_denied(name, denied) for name in self._referenced_names):
                allowed.append(user.id)
        return allowed


def notify_check_started_failing(check: DataQualityCheck, failed_row_count: int | None) -> None:
    """Best-effort: a notification failure must never take down the run that produced it."""
    try:
        if not is_data_quality_checks_enabled_for_team_id(check.team_id) or check.subject_uuid is None:
            return
        team = Team.objects.get(id=check.team_id)
        create_notification(
            NotificationData(
                team_id=check.team_id,
                notification_type=NotificationType.DATA_QUALITY_CHECK_FAILURE,
                priority=Priority.NORMAL,
                title=f"Data quality check failed on {check.subject_name}",
                body=_body(check, failed_row_count),
                target_type=TargetType.TEAM,
                target_id=str(check.team_id),
                # The body names a warehouse table or view and one of its columns, so it points at
                # the subject object (not the check) and the resolver filters recipients down to
                # members with object-level access to it, plus query access for the count.
                resource_type="warehouse_objects",
                resource_id=str(check.subject_uuid),
                resolver=_WarehouseSubjectResolver(
                    team,
                    check.subject_type,
                    str(check.subject_uuid),
                    referenced_names=referenced_subject_names(team.id, check.check_type, check.config),
                ),
            )
        )
    except Exception:
        LOGGER.exception("Could not send a data quality failure notification", check_id=str(check.id))


def notify_materialization_blocked(
    team_id: int, saved_query_id: str, view_name: str, blocking_failures: int, job_id: str
) -> None:
    """Tell the team a refresh was not published because its checks failed. Best-effort."""
    try:
        if not is_data_quality_checks_enabled_for_team_id(team_id):
            return
        team = Team.objects.get(id=team_id)
        checks = "check" if blocking_failures == 1 else "checks"
        create_notification(
            NotificationData(
                team_id=team_id,
                notification_type=NotificationType.DATA_QUALITY_CHECK_FAILURE,
                priority=Priority.NORMAL,
                title=f"Materialization of {view_name} was not published",
                body=f"{blocking_failures} data quality {checks} failed, so the previous version keeps "
                "serving. Fix the data or the checks, then materialize again.",
                target_type=TargetType.TEAM,
                target_id=str(team_id),
                resource_type="warehouse_objects",
                resource_id=saved_query_id,
                # Keyed on the blocked materialization job: the block activity can run twice when a
                # slow attempt hits its start-to-close timeout, and the unique constraint behind this
                # key collapses the retry to one notice while a genuinely new block notifies again.
                idempotency_key=f"matview-blocked-{job_id}",
                resolver=_WarehouseSubjectResolver(
                    team,
                    SubjectType.VIEW,
                    saved_query_id,
                    referenced_names=_blocking_referenced_names(team_id, saved_query_id, job_id),
                ),
            )
        )
    except Exception:
        LOGGER.exception("Could not send a materialization-blocked notification", saved_query_id=saved_query_id)


def _blocking_referenced_names(team_id: int, saved_query_id: str, job_id: str) -> list[str]:
    """Every further subject the checks behind a blocked materialization read.

    The body's failure count aggregates those checks, so it is an oracle over everything they read,
    not just over the view the recipient is already allowed to see.

    Read off the suite's persisted check runs, not the definitions' current state. ``enabled``,
    ``severity``, ``last_status`` and ``deleted`` are all writable by anyone who can edit the view --
    including a member denied a subject the check reads, since the write path only authorizes the
    declared subject. Selecting on them would let that member edit their own denial out of this
    filter in the window between the suite finishing and this notice being written, while the count
    still counts their check. A run row is immutable, so it cannot be edited out of the set it
    belongs to. The suite is the one the blocked job triggered, so the names and the count come from
    the same batch, across every subject the batch covered.
    """
    names: set[str] = set()
    runs = (
        DataQualityCheckRun.objects.for_team(team_id)
        .filter(
            suite_run__data_modeling_job_id=job_id,
            status=CheckRunStatus.FAILED,
            # No severity on the run row, so this takes warn-severity failures too. They did not
            # block, so the set is wider than the count -- which over-filters rather than leaks.
            check_type__in=referencing_check_types(),
        )
        .select_related("quality_check")
    )
    # A run records which check ran, never the config it ran with. A definition that has since been
    # hard-deleted or re-pointed at other tables leaves nothing to enumerate, and so does a suite
    # retention already swept. Widen to every referencing check on the subject: wider than this
    # block, but it can only drop more recipients, never admit one the count would leak to.
    unbindable = not DataQualitySuiteRun.objects.for_team(team_id).filter(data_modeling_job_id=job_id).exists()
    for run in runs:
        check = run.quality_check
        if check is None or check.fingerprint != run.check_fingerprint:
            unbindable = True
            continue
        names.update(referenced_subject_names(team_id, check.check_type, check.config))
    if unbindable:
        for check in checks_for_subject(team_id, SubjectType.VIEW, saved_query_id, include_deleted=True).filter(
            check_type__in=referencing_check_types()
        ):
            names.update(referenced_subject_names(team_id, check.check_type, check.config))
    return sorted(names)


def _body(check: DataQualityCheck, failed_row_count: int | None) -> str:
    subject = f"{check.check_type} check"
    if check.column_name:
        subject = f"{check.check_type} check on {check.subject_name}.{check.column_name}"

    if failed_row_count:
        rows = "row" if failed_row_count == 1 else "rows"
        return f"The {subject} found {failed_row_count} failing {rows}. It was passing on the previous run."
    return f"The {subject} started failing. It was passing on the previous run."
