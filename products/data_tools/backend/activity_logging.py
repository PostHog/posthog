"""Activity-log receivers for warehouse expressions and joins.

``ModelActivityMixin`` emits ``model_activity_signal`` on every save; these persist the
audit trail (create, edit, soft delete, restore). Registered from ``apps.ready()``.
"""

from typing import Any, Optional

from posthog.models import User
from posthog.models.activity_logging.activity_log import log_activity_with_soft_delete
from posthog.models.signals import model_activity_signal, mutable_receiver

from .models.expression import DataWarehouseExpression
from .models.join import DataWarehouseJoin


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

    log_activity_with_soft_delete(
        previous=before_update,
        current=after_update,
        user=user,
        was_impersonated=was_impersonated,
        scope=scope,
        activity=activity,
        name=f"{instance.table_name}.{instance.field_name}",
    )


@mutable_receiver(model_activity_signal, sender=DataWarehouseJoin)
def handle_join_activity(
    sender: type,
    scope: str,
    before_update: Optional[DataWarehouseJoin],
    after_update: Optional[DataWarehouseJoin],
    activity: str,
    user: Optional[User],
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    join = after_update or before_update
    if join is None:
        return

    log_activity_with_soft_delete(
        previous=before_update,
        current=after_update,
        user=user,
        was_impersonated=was_impersonated,
        scope=scope,
        activity=activity,
        name=f"{join.source_table_name}.{join.field_name}",
        # The org-wide activity route filters on organization_id.
        organization_id=join.team.organization_id,
    )
