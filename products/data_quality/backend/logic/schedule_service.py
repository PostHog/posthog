from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import UUID

from posthog.dataclasses import frozen

from ..activity_logging import log_schedule_change
from ..facade.enums import SubjectType, SuiteRunTrigger
from ..models import DataQualitySuiteRun
from .schedules import CheckSchedule, get_schedule, get_schedules, update_schedule_with_snapshots
from .subject_access import suites_backing_unreadable_runs_q, unreadable_suites_q

if TYPE_CHECKING:
    from posthog.models import User

    from .subject_access import DenialContext


def schedule_with_history(
    team_id: int,
    subject_type: SubjectType,
    subject_uuid: str | UUID,
    schedule: CheckSchedule,
    authorization_context: DenialContext | None = None,
) -> CheckSchedule:
    suites = DataQualitySuiteRun.objects.for_team(team_id).filter(
        subject_type=subject_type,
        subject_uuid=subject_uuid,
        trigger=SuiteRunTrigger.SCHEDULED,
    )
    if authorization_context is not None:
        suites = suites.exclude(unreadable_suites_q(authorization_context)).exclude(
            suites_backing_unreadable_runs_q(team_id, authorization_context)
        )
    last_suite = suites.order_by("-started_at", "-id").first()
    if last_suite is None:
        return schedule
    return replace(schedule, last_run_at=last_suite.started_at, last_suite_run=last_suite.id)


@frozen
class SubjectSchedule:
    subject_type: SubjectType
    subject_uuid: UUID
    schedule: CheckSchedule


def list_schedules_with_history(
    team_id: int,
    subjects: Sequence[tuple[SubjectType, UUID]],
    authorization_context: DenialContext | None = None,
) -> list[SubjectSchedule]:
    """Every subject's schedule with its last visible scheduled run, over one Temporal round trip and one query."""
    schedules = get_schedules(team_id, subjects)
    suites = DataQualitySuiteRun.objects.for_team(team_id).filter(
        trigger=SuiteRunTrigger.SCHEDULED,
        subject_type__in={str(subject_type) for subject_type, _ in subjects},
        subject_uuid__in=[subject_uuid for _, subject_uuid in subjects],
    )
    if authorization_context is not None:
        suites = suites.exclude(unreadable_suites_q(authorization_context)).exclude(
            suites_backing_unreadable_runs_q(team_id, authorization_context)
        )
    last_suites = {
        (suite.subject_type, suite.subject_uuid): suite
        for suite in suites.order_by("subject_type", "subject_uuid", "-started_at", "-id").distinct(
            "subject_type", "subject_uuid"
        )
    }
    rows: list[SubjectSchedule] = []
    for key, schedule in schedules.items():
        last_suite = last_suites.get((str(key.subject_type), key.subject_uuid))
        if last_suite is not None:
            schedule = replace(schedule, last_run_at=last_suite.started_at, last_suite_run=last_suite.id)
        rows.append(SubjectSchedule(subject_type=key.subject_type, subject_uuid=key.subject_uuid, schedule=schedule))
    return rows


def get_schedule_with_history(
    team_id: int,
    subject_type: SubjectType,
    subject_uuid: str | UUID,
    authorization_context: DenialContext | None = None,
) -> CheckSchedule | None:
    schedule = get_schedule(team_id, subject_type, subject_uuid)
    if schedule is None:
        return None
    return schedule_with_history(team_id, subject_type, subject_uuid, schedule, authorization_context)


def update_schedule(
    team_id: int,
    subject_type: SubjectType,
    subject_uuid: str | UUID,
    *,
    user: User,
    authorization_context: DenialContext | None = None,
    interval: str | None = None,
    enabled: bool | None = None,
) -> CheckSchedule:
    result = update_schedule_with_snapshots(
        team_id,
        subject_type,
        subject_uuid,
        interval=interval,
        enabled=enabled,
    )
    log_schedule_change(team_id, str(subject_type), str(subject_uuid), result.before, result.after, user)
    return schedule_with_history(team_id, subject_type, subject_uuid, result.after, authorization_context)
