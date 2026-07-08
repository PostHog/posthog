"""Activity-log receiver for catalog metrics.

``ModelActivityMixin`` emits ``model_activity_signal`` on every metric save; this persists the audit
trail (create, approve, definition change, soft delete). Registered from ``apps.ready()``.
"""

from typing import Any, Optional

from posthog.models import User
from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver

from .models import Metric


@mutable_receiver(model_activity_signal, sender=Metric)
def handle_metric_activity(
    sender: type,
    scope: str,
    before_update: Optional[Metric],
    after_update: Optional[Metric],
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
            name=instance.name,
            changes=changes_between(scope, previous=before_update, current=after_update),
        ),
    )
