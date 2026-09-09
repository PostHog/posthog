from datetime import datetime
from uuid import UUID

from django.utils import timezone

from posthog.models.scoping.manager import resolve_effective_team_id

from ..models import DataQualityCheckSchedule


def get_or_create_schedule(
    team_id: int,
    subject_type: str,
    subject_uuid: str | UUID,
    *,
    now: datetime | None = None,
    created_by_id: int | None = None,
) -> DataQualityCheckSchedule:
    # A child environment's row is filed under its parent by the save() rewrite, so look it up and
    # create it there too. Scoping to the parent while filtering on the child's own id matches
    # nothing, and the next subject then hits the unique constraint instead of its own schedule.
    canonical_team_id = resolve_effective_team_id(team_id)
    schedule, _ = DataQualityCheckSchedule.objects.for_team(canonical_team_id, canonical=True).get_or_create(
        team_id=canonical_team_id,
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
