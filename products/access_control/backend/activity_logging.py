"""Activity-log receiver for access control rules.

``ModelActivityMixin`` emits ``model_activity_signal`` when a rule is saved or deleted. This
persists who granted, changed, or removed access. Registered from ``apps.ready()``.
"""

import dataclasses
from typing import Any, Literal, Optional

from django.db.models.signals import pre_delete

from posthog.models import User
from posthog.models.activity_logging.activity_log import (
    ActivityContextBase,
    Change,
    Detail,
    LogActivityEntry,
    changes_between,
    log_activity,
)
from posthog.models.activity_logging.model_activity import get_current_user, get_was_impersonated
from posthog.models.signals import model_activity_signal, mutable_receiver

from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.role import Role, RoleMembership


@dataclasses.dataclass(frozen=True)
class AccessControlContext(ActivityContextBase):
    resource: str
    resource_id: str | None
    access_level: str
    role_id: str | None
    organization_member_id: str | None


def get_access_control_log_entry(
    *,
    before_update: Optional[AccessControl],
    after_update: Optional[AccessControl],
    activity: str,
    user: Optional[User],
    was_impersonated: bool = False,
) -> LogActivityEntry | None:
    rule = after_update or before_update
    if rule is None:
        return None

    if activity == "created":
        changes = [Change(type="AccessControl", field="access_level", action="created", after=rule.access_level)]
    elif activity == "deleted":
        changes = [Change(type="AccessControl", field="access_level", action="deleted", before=rule.access_level)]
    else:
        changes = changes_between("AccessControl", previous=before_update, current=after_update)

    return LogActivityEntry(
        organization_id=rule.team.organization_id,
        team_id=rule.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=rule.id,
        scope="AccessControl",
        activity=activity,
        detail=Detail(
            name=f"{rule.resource} {rule.resource_id}" if rule.resource_id else rule.resource,
            changes=changes,
            context=AccessControlContext(
                resource=rule.resource,
                resource_id=rule.resource_id,
                access_level=rule.access_level,
                # Ids only: any activity-log reader sees this row, so it carries no names or emails.
                role_id=str(rule.role_id) if rule.role_id else None,
                organization_member_id=str(rule.organization_member_id) if rule.organization_member_id else None,
            ),
        ),
    )


@mutable_receiver(model_activity_signal, sender=AccessControl)
def handle_access_control_change(
    sender: type,
    scope: str,
    before_update: Optional[AccessControl],
    after_update: Optional[AccessControl],
    activity: str,
    user: Optional[User],
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    entry = get_access_control_log_entry(
        before_update=before_update,
        after_update=after_update,
        activity=activity,
        user=user,
        was_impersonated=was_impersonated,
    )
    if entry is not None:
        log_activity(**entry)


@mutable_receiver(model_activity_signal, sender=Role)
def handle_role_change(
    sender: type,
    scope: str,
    before_update: Role | None,
    after_update: Role | None,
    activity: Literal["created", "updated", "deleted"],
    user: User | None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    role = after_update or before_update
    if role is None:
        return
    log_activity(
        organization_id=role.organization_id,
        team_id=None,
        user=user,
        was_impersonated=was_impersonated,
        item_id=role.id,
        scope="Role",
        activity=activity,
        detail=Detail(
            name=role.name,
            changes=[
                Change(
                    type="Role",
                    field=field,
                    action="changed" if activity == "updated" else activity,
                    before=getattr(before_update, field, None),
                    after=getattr(after_update, field, None),
                )
                for field in ("name", "organization_access_level")
                if getattr(before_update, field, None) != getattr(after_update, field, None)
            ],
        ),
    )


@mutable_receiver(model_activity_signal, sender=RoleMembership)
def handle_role_membership_change(
    sender: type,
    scope: str,
    before_update: RoleMembership | None,
    after_update: RoleMembership | None,
    activity: Literal["created", "updated", "deleted"],
    user: User | None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    membership = after_update or before_update
    if membership is None:
        return
    if activity == "created":
        _log_role_member_change(membership, "created", user, was_impersonated)
    elif before_update is not None and (
        before_update.organization_member_id != membership.organization_member_id
        or before_update.user_id != membership.user_id
        or before_update.role_id != membership.role_id
    ):
        _log_role_member_change(before_update, "deleted", user, was_impersonated)
        _log_role_member_change(membership, "created", user, was_impersonated)


def _log_role_member_change(
    membership: RoleMembership, action: Literal["created", "deleted"], user: User | None, was_impersonated: bool
) -> None:
    role = membership.role
    if role.organization_access_level is None:
        return
    log_activity(
        organization_id=role.organization_id,
        team_id=None,
        user=user,
        was_impersonated=was_impersonated,
        item_id=role.id,
        scope="Role",
        activity="updated",
        detail=Detail(
            name=role.name,
            changes=[
                Change(
                    type="Role",
                    field="members",
                    action=action,
                    before=membership.user_id if action == "deleted" else None,
                    after=membership.user_id if action == "created" else None,
                )
            ],
        ),
    )


@mutable_receiver(pre_delete, sender=RoleMembership)
def handle_role_membership_delete(sender: type, instance: RoleMembership, **kwargs: Any) -> None:
    _log_role_member_change(instance, "deleted", get_current_user(), get_was_impersonated())


@mutable_receiver(pre_delete, sender=Role)
def handle_role_delete(sender: type, instance: Role, **kwargs: Any) -> None:
    handle_role_change(
        sender=sender,
        scope="Role",
        before_update=instance,
        after_update=None,
        activity="deleted",
        user=get_current_user(),
        was_impersonated=get_was_impersonated(),
    )
