"""Activity-log receiver for data quality checks.

``ModelActivityMixin`` emits ``model_activity_signal`` on every check save; this persists the audit
trail (create, config change, soft delete). Registered from ``apps.ready()``.
"""

from typing import Any, Optional, cast

from posthog.models import User
from posthog.models.activity_logging.activity_log import AuditableScope, Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver

from .models import DataQualityCheck


@mutable_receiver(model_activity_signal, sender=DataQualityCheck)
def handle_data_quality_check_activity(
    sender: type,
    scope: str,
    before_update: Optional[DataQualityCheck],
    after_update: Optional[DataQualityCheck],
    activity: str,
    user: Optional[User],
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    instance = after_update or before_update
    if instance is None:
        return
    log_activity(
        organization_id=None,
        team_id=instance.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=str(instance.id),
        scope=scope,
        activity=activity,
        detail=Detail(
            name=str(instance),
            changes=changes_between(cast(AuditableScope, scope), previous=before_update, current=after_update),
        ),
    )
