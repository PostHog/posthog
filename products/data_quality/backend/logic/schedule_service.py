from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import UUID

from ..activity_logging import log_metric_schedule_change
from ..facade.enums import SuiteRunTrigger
from ..models import DataQualitySuiteRun
from .schedules import MetricCheckSchedule, get_schedule, update_schedule_with_snapshots
from .subject_access import suites_backing_unreadable_runs_q, unreadable_suites_q

if TYPE_CHECKING:
    from posthog.models import User

    from ..facade.enums import SubjectType
    from .subject_access import DenialContext


def schedule_with_history(
    team_id: int,
    subject_type: SubjectType,
    subject_uuid: str | UUID,
    schedule: MetricCheckSchedule,
    authorization_context: DenialContext | None = None,
) -> MetricCheckSchedule:
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


def get_schedule_with_history(
    team_id: int,
    subject_type: SubjectType,
    subject_uuid: str | UUID,
    authorization_context: DenialContext | None = None,
) -> MetricCheckSchedule | None:
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
) -> MetricCheckSchedule:
    result = update_schedule_with_snapshots(
        team_id,
        subject_type,
        subject_uuid,
        interval=interval,
        enabled=enabled,
    )
    log_metric_schedule_change(team_id, str(subject_uuid), result.before, result.after, user)
    return schedule_with_history(team_id, subject_type, subject_uuid, result.after, authorization_context)
