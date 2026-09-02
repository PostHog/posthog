"""Activity-log receiver for warehouse expressions.

``ModelActivityMixin`` emits ``model_activity_signal`` on every expression save; this persists the
audit trail (create, edit, soft delete, restore). Registered from ``apps.ready()``.
"""

from typing import Any, Optional, cast

from posthog.models import User
from posthog.models.activity_logging.activity_log import AuditableScope, Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver

from .models.expression import DataWarehouseExpression


@mutable_receiver(model_activity_signal, sender=DataWarehouseExpression)
def handle_expression_activity(
    sender: type,
    scope: str,
    before_update: Optional[DataWarehouseExpression],
    after_update: Optional[DataWarehouseExpression],
    activity: str,
    user: Optional[User],
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    instance = after_update or before_update
    if instance is None:
        return

    changes = changes_between(cast(AuditableScope, scope), previous=before_update, current=after_update)

    # Soft delete and restore go through save(), so the mixin reports them as "updated";
    # remap so the audit trail reads as the action the user actually took.
    deleted_change = next((change for change in changes if change.field == "deleted"), None)
    if deleted_change:
        activity = "deleted" if deleted_change.after else "restored"

    log_activity(
        organization_id=None,
        team_id=instance.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=str(instance.id),
        scope=scope,
        activity=activity,
        detail=Detail(name=f"{instance.table_name}.{instance.field_name}", changes=changes),
    )
