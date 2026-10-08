"""Activity-log receiver for warehouse expressions.

``ModelActivityMixin`` emits ``model_activity_signal`` on every expression save; this persists the
audit trail (create, edit, soft delete, restore). Registered from ``apps.ready()``.
"""

from typing import Any, Optional

from posthog.models import User
from posthog.models.activity_logging.activity_log import log_activity_with_soft_delete
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

    log_activity_with_soft_delete(
        previous=before_update,
        current=after_update,
        user=user,
        was_impersonated=was_impersonated,
        scope=scope,
        activity=activity,
        name=f"{instance.table_name}.{instance.field_name}",
    )
