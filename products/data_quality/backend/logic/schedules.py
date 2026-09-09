from datetime import datetime
from uuid import UUID

from django.utils import timezone

from ..models import DataQualityCheckSchedule


def get_or_create_schedule(
    team_id: int,
    subject_type: str,
    subject_uuid: str | UUID,
    *,
    now: datetime | None = None,
    created_by_id: int | None = None,
) -> DataQualityCheckSchedule:
    schedule, _ = DataQualityCheckSchedule.objects.for_team(team_id).get_or_create(
        team_id=team_id,
        subject_type=subject_type,
        subject_uuid=subject_uuid,
        defaults={"next_run_at": now or timezone.now(), "created_by_id": created_by_id},
    )
    return schedule


def get_schedule(team_id: int, subject_type: str, subject_uuid: str | UUID) -> DataQualityCheckSchedule | None:
    return (
        DataQualityCheckSchedule.objects.for_team(team_id)
        .filter(subject_type=subject_type, subject_uuid=subject_uuid)
        .first()
    )
