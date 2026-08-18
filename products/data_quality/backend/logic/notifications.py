"""Tell the team when a model starts failing its checks.

Only the pass-to-fail edge notifies, and only for error-severity checks. A check that keeps failing
run after run is already known about; re-notifying every run is how an inbox gets ignored.
"""

from typing import cast

import structlog

from posthog.models import Team, User
from posthog.rbac.user_access_control import UserAccessControl, access_level_satisfied_for_resource
from posthog.scopes import APIScopeObject

from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    RecipientsResolver,
    TargetType,
    create_notification,
)

from ..facade.enums import SubjectType
from ..models import DataQualityCheck
from .flags import is_data_quality_checks_enabled_for_team_id
from .subject_access import denied_subject_names, is_subject_denied, referenced_subject_names

LOGGER = structlog.get_logger(__name__)

# Object-level access controls for a warehouse table or view are keyed on the child resource; both
# inherit from the `warehouse_objects` umbrella the built-in resource-level filter checks.
_SUBJECT_RESOURCE: dict[SubjectType, APIScopeObject] = {
    SubjectType.TABLE: cast(APIScopeObject, "warehouse_table"),
    SubjectType.VIEW: cast(APIScopeObject, "warehouse_view"),
}


class _WarehouseSubjectResolver(RecipientsResolver):
    """Drop members who must not receive this check's warehouse metadata or its failing-row count.

    Two gates on top of the built-in resource-level `warehouse_objects` filter that
    `create_notification` runs:

    - **Object-level** access to *this* table or view. The resource-level filter only asks whether a
      member can see warehouse objects at all, so a member with general warehouse access but an
      explicit denial on the subject would still receive its name, column, check type, and count.
    - **Referenced-subject** access. A `relationships` check reads a second subject and a `custom_sql`
      check reads arbitrary tables, so `failed_row_count` is a count oracle over those too. A member
      denied any subject the check reads must be dropped, matching how the run-history API gates them.
    - **Query** viewer access. The body's `failed_row_count` is a count oracle over the underlying
      warehouse rows that the run-history API gates behind query access, so a member denied `query`
      must not read it from the notification either.
    """

    def __init__(
        self,
        team: Team,
        subject_type: str,
        subject_uuid: str,
        check: DataQualityCheck | None = None,
    ) -> None:
        self._team = team
        self._subject_type = subject_type
        self._subject_uuid = subject_uuid
        self._check = check

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

        # When access controls aren't available for the org, the built-in filter lets everyone
        # through; match that here rather than dropping the whole team.
        sample = User.objects.filter(id__in=user_ids).first()
        if sample is None or not UserAccessControl(sample, self._team).access_controls_supported:
            return user_ids

        allowed: list[int] = []
        for user in User.objects.filter(id__in=user_ids):
            level = (
                UserAccessControl(user, self._team)
                .bulk_object_access_levels(resource, [(object_id, None)])
                .get(object_id)
            )
            if level is not None and access_level_satisfied_for_resource(resource, level, "viewer"):
                allowed.append(user.id)
        return allowed

    def _filter_by_referenced_subject_access(self, user_ids: list[int]) -> list[int]:
        # The declared subject isn't the only one the count depends on: a relationships check reads
        # its target and a custom_sql check reads arbitrary tables. Drop members denied any of those,
        # matching the run-history endpoint -- resolved by name the same way the loaders resolve them.
        if self._check is None:
            return user_ids
        names = referenced_subject_names(self._team.id, self._check.check_type, self._check.config)
        if not names:
            return user_ids

        allowed: list[int] = []
        for user in User.objects.filter(id__in=user_ids):
            denied = denied_subject_names(self._team, user)
            if not any(is_subject_denied(name, denied) for name in names):
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
                resolver=_WarehouseSubjectResolver(team, check.subject_type, str(check.subject_uuid), check=check),
            )
        )
    except Exception:
        LOGGER.exception("Could not send a data quality failure notification", check_id=str(check.id))


def notify_materialization_blocked(team_id: int, saved_query_id: str, view_name: str, blocking_failures: int) -> None:
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
                resolver=_WarehouseSubjectResolver(team, SubjectType.VIEW, saved_query_id),
            )
        )
    except Exception:
        LOGGER.exception("Could not send a materialization-blocked notification", saved_query_id=saved_query_id)


def _body(check: DataQualityCheck, failed_row_count: int | None) -> str:
    subject = f"{check.check_type} check"
    if check.column_name:
        subject = f"{check.check_type} check on {check.subject_name}.{check.column_name}"

    if failed_row_count:
        rows = "row" if failed_row_count == 1 else "rows"
        return f"The {subject} found {failed_row_count} failing {rows}. It was passing on the previous run."
    return f"The {subject} started failing. It was passing on the previous run."
