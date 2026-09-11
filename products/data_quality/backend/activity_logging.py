"""Activity-log receiver for data quality checks.

``ModelActivityMixin`` emits ``model_activity_signal`` on every check save; this persists the audit
trail (create, config change, soft delete). Registered from ``apps.ready()``.
"""

from typing import TYPE_CHECKING, Any, Optional, cast

from posthog.models import User
from posthog.models.activity_logging.activity_log import AuditableScope, Change, Detail, changes_between, log_activity
from posthog.models.activity_logging.model_activity import get_was_impersonated
from posthog.models.signals import model_activity_signal, mutable_receiver

from .models import DataQualityCheck

if TYPE_CHECKING:
    from .logic.schedules import MetricCheckSchedule


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


def log_metric_schedule_change(
    team_id: int,
    metric_id: str,
    before: "MetricCheckSchedule",
    after: "MetricCheckSchedule",
    user: User,
) -> None:
    from .logic.subjects import resolve_subject  # noqa: PLC0415 — avoids loading the catalog during Django startup

    changes = [
        Change(
            type="DataQualityCheckSchedule",
            field=field,
            action="changed",
            before=getattr(before, field),
            after=getattr(after, field),
        )
        for field in ("interval", "enabled")
        if getattr(before, field) != getattr(after, field)
    ]
    if not changes:
        return
    subject = resolve_subject(team_id, "metric", metric_id)
    log_activity(
        organization_id=None,
        team_id=team_id,
        user=user,
        was_impersonated=get_was_impersonated(),
        item_id=str(after.id),
        scope="DataQualityCheckSchedule",
        activity="updated",
        detail=Detail(name=f"metric check schedule on {subject.name or metric_id}", changes=changes),
    )
