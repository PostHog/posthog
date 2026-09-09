"""Activity-log receiver for data quality checks.

``ModelActivityMixin`` emits ``model_activity_signal`` on every check save; this persists the audit
trail (create, config change, soft delete). Registered from ``apps.ready()``.
"""

from typing import Any, Optional, cast

from posthog.models import User
from posthog.models.activity_logging.activity_log import AuditableScope, Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver

from .logic.subjects import resolve_subject
from .models import DataQualityCheck, DataQualityCheckSchedule


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


@mutable_receiver(model_activity_signal, sender=DataQualityCheckSchedule)
def handle_data_quality_schedule_activity(
    sender: type,
    scope: str,
    before_update: DataQualityCheckSchedule | None,
    after_update: DataQualityCheckSchedule | None,
    activity: str,
    user: User | None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    instance = after_update or before_update
    if instance is None:
        return
    # The reader sees only this name: no describer is registered for the scope, and the subject
    # columns are excluded from the change diff. Without the subject, every schedule reads alike.
    subject = resolve_subject(instance.team_id, instance.subject_type, instance.subject_uuid)
    log_activity(
        organization_id=None,
        team_id=instance.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=str(instance.id),
        scope=scope,
        activity=activity,
        detail=Detail(
            name=f"{instance.subject_type} check schedule on {subject.name or instance.subject_uuid}",
            changes=changes_between(cast(AuditableScope, scope), previous=before_update, current=after_update),
        ),
    )
