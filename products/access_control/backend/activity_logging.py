"""Activity-log receiver for access control rules.

``ModelActivityMixin`` emits ``model_activity_signal`` when a rule is saved or deleted. This
persists who granted, changed, or removed access. Registered from ``apps.ready()``.
"""

import dataclasses
from typing import Any, Optional

from posthog.models import User
from posthog.models.activity_logging.activity_log import (
    ActivityContextBase,
    Change,
    Detail,
    changes_between,
    log_activity,
)
from posthog.models.signals import model_activity_signal, mutable_receiver

from products.access_control.backend.models.access_control import AccessControl


@dataclasses.dataclass(frozen=True)
class AccessControlContext(ActivityContextBase):
    resource: str
    resource_id: str | None
    access_level: str
    role_id: str | None
    organization_member_id: str | None


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
    rule = after_update or before_update
    if rule is None:
        return

    if activity == "created":
        changes = [Change(type="AccessControl", field="access_level", action="created", after=rule.access_level)]
    elif activity == "deleted":
        changes = [Change(type="AccessControl", field="access_level", action="deleted", before=rule.access_level)]
    else:
        changes = changes_between("AccessControl", previous=before_update, current=after_update)

    log_activity(
        organization_id=rule.team.organization_id,
        team_id=rule.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=rule.id,
        scope=scope,
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
