from datetime import UTC, datetime, timedelta
from uuid import UUID

from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

import structlog

from posthog.models.scoping.manager import resolve_effective_team_id

from products.warehouse_sources.backend.facade.models import sync_frequency_to_sync_frequency_interval

from ..facade.enums import ScheduleInterval, SubjectType
from ..models import DataQualityCheck, DataQualityCheckSchedule
from .contracts import ClaimedScheduleBatch, DueSchedule
from .flags import get_data_quality_checks_flag_for_team_id

DISPATCH_INTERVAL = timedelta(minutes=15)
GRID_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
logger = structlog.get_logger(__name__)


def interval_from_label(label: str) -> timedelta:
    label = ScheduleInterval(label)
    interval = sync_frequency_to_sync_frequency_interval(label)
    if interval is None:
        raise ValueError(f"Unsupported schedule interval: {label}")
    return interval


def label_from_interval(interval: timedelta) -> ScheduleInterval:
    for label in ScheduleInterval:
        if interval_from_label(label) == interval:
            return label
    raise ValueError(f"Unsupported schedule interval: {interval}")


def schedule_offset(schedule_id: UUID, interval: timedelta) -> timedelta:
    slots = max(1, interval // DISPATCH_INTERVAL)
    return DISPATCH_INTERVAL * (schedule_id.int % slots)


def next_run_after(
    previous: datetime | None, interval: timedelta, now: datetime, offset: timedelta = timedelta(0)
) -> datetime:
    if interval <= timedelta(0):
        raise ValueError("Schedule interval must be positive.")
    next_at = (previous or now) + interval
    if next_at <= now:
        next_at += interval * ((now - next_at) // interval + 1)
    snapped = GRID_EPOCH + interval * ((next_at - GRID_EPOCH) // interval) + offset
    # Flooring to the grid can land before next_at, which would fire again inside one interval of
    # the previous run. Take the next slot instead, so the cadence holds. A schedule that has never
    # run has no previous run to space away from, so its first run may snap down.
    if previous is not None and snapped < next_at:
        snapped += interval
    if snapped <= now:
        snapped += interval
    return snapped


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


def set_schedule(
    team_id: int,
    subject_type: str,
    subject_uuid: str | UUID,
    *,
    interval: str | None = None,
    enabled: bool | None = None,
    now: datetime | None = None,
) -> DataQualityCheckSchedule:
    cadence = interval_from_label(interval) if interval is not None else None
    if enabled is not None and not isinstance(enabled, bool):
        raise ValueError("Schedule enabled must be a boolean.")
    now = now or timezone.now()
    with transaction.atomic():
        schedule = (
            DataQualityCheckSchedule.objects.for_team(team_id)
            .select_for_update()
            .get(subject_type=subject_type, subject_uuid=subject_uuid)
        )
        changed = []
        if cadence is not None and cadence != schedule.interval:
            schedule.interval = cadence
            schedule.next_run_at = next_run_after(
                schedule.last_run_at, cadence, now, schedule_offset(schedule.id, cadence)
            )
            changed.extend(["interval", "next_run_at"])
        if enabled is not None and enabled != schedule.enabled:
            schedule.enabled = enabled
            changed.append("enabled")
        if changed:
            schedule.save(update_fields=[*changed, "updated_at"])
        return schedule


def claim_due_schedules(
    now: datetime, limit: int, *, enabled_teams: dict[int, bool] | None = None
) -> list[DueSchedule]:
    return claim_due_schedule_batch(now, limit, enabled_teams=enabled_teams).schedules


def claim_due_schedule_batch(
    now: datetime, limit: int, *, enabled_teams: dict[int, bool] | None = None, after: DueSchedule | None = None
) -> ClaimedScheduleBatch:
    if limit <= 0:
        return ClaimedScheduleBatch(claimed_count=0, schedules=[])
    # A deleted metric is soft-deleted, so the FK never runs the orphan handler that would take its
    # checks out of this subquery. Read the metric's own state instead, or the schedule keeps firing
    # suites that resolve no subject, once per cadence, until the daily sweep reaps the rows.
    enabled_checks = (
        DataQualityCheck.objects.unscoped()
        .filter(team_id=OuterRef("team_id"), subject_type=OuterRef("subject_type"), enabled=True, deleted=False)
        .filter(subject_type=SubjectType.METRIC, metric_id=OuterRef("subject_uuid"))
        .exclude(metric__deleted=True)
    )
    candidates = (
        DataQualityCheckSchedule.objects.unscoped()
        .filter(subject_type=SubjectType.METRIC, enabled=True, next_run_at__lte=now)
        .filter(Exists(enabled_checks))
    )
    if after is not None:
        candidates = candidates.filter(
            Q(next_run_at__gt=after.fire_at) | Q(next_run_at=after.fire_at, id__gt=after.schedule_id)
        )
    due = [
        DueSchedule(
            team_id=schedule.team_id,
            schedule_id=schedule.id,
            subject_type=schedule.subject_type,
            subject_uuid=schedule.subject_uuid,
            fire_at=schedule.next_run_at,
        )
        for schedule in candidates.order_by("next_run_at", "id")[:limit]
    ]
    flags = enabled_teams if enabled_teams is not None else {}
    failed_teams: set[int] = set()
    runnable: list[DueSchedule] = []
    skipped: list[DueSchedule] = []
    for schedule in due:
        if schedule.team_id in failed_teams:
            continue
        if schedule.team_id not in flags:
            try:
                enabled = get_data_quality_checks_flag_for_team_id(schedule.team_id)
            except Exception:
                logger.exception("data_quality_schedule_flag_lookup_failed", team_id=schedule.team_id)
                failed_teams.add(schedule.team_id)
                continue
            if enabled is None:
                logger.warning("data_quality_schedule_flag_indeterminate", team_id=schedule.team_id)
                failed_teams.add(schedule.team_id)
                continue
            flags[schedule.team_id] = enabled
        (runnable if flags[schedule.team_id] else skipped).append(schedule)
    return ClaimedScheduleBatch(
        claimed_count=len(due),
        schedules=runnable,
        skipped_schedules=skipped,
        next_cursor=due[-1] if due else None,
    )


def acknowledge_schedule(occurrence: DueSchedule, now: datetime) -> bool:
    with transaction.atomic():
        schedule = (
            DataQualityCheckSchedule.objects.for_team(occurrence.team_id)
            .select_for_update()
            .filter(id=occurrence.schedule_id, next_run_at=occurrence.fire_at)
            .first()
        )
        if schedule is None:
            return False
        schedule.next_run_at = next_run_after(
            occurrence.fire_at, schedule.interval, now, schedule_offset(schedule.id, schedule.interval)
        )
        schedule.save(update_fields=["next_run_at", "updated_at"])
        return True
