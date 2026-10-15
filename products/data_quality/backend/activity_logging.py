"""Activity-log receiver for data quality checks.

``ModelActivityMixin`` emits ``model_activity_signal`` on every check save; this persists the audit
trail (create, config change, soft delete). Registered from ``apps.ready()``.
"""

from typing import TYPE_CHECKING, Any, Optional

from posthog.models import User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity, log_activity_with_soft_delete
from posthog.models.activity_logging.model_activity import get_was_impersonated
from posthog.models.signals import model_activity_signal, mutable_receiver

from .models import DataQualityCheck

if TYPE_CHECKING:
    from .logic.schedules import CheckSchedule


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
    log_activity_with_soft_delete(
        previous=before_update,
        current=after_update,
        user=user,
        was_impersonated=was_impersonated,
        scope=scope,
        activity=activity,
    )


def log_schedule_change(
    team_id: int,
    subject_type: str,
    subject_uuid: str,
    before: "CheckSchedule",
    after: "CheckSchedule",
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
    subject = resolve_subject(team_id, subject_type, subject_uuid)
    log_activity(
        organization_id=None,
        team_id=team_id,
        user=user,
        was_impersonated=get_was_impersonated(),
        item_id=str(after.id),
        scope="DataQualityCheckSchedule",
        activity="updated",
        detail=Detail(name=f"{subject_type} check schedule on {subject.name or subject_uuid}", changes=changes),
    )
