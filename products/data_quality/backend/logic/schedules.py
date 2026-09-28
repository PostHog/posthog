import asyncio
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

import structlog
from asgiref.sync import async_to_sync, sync_to_async
from temporalio.client import ScheduleDescription

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.temporal.common.client import async_connect

from ..facade.enums import ScheduleInterval, SubjectType
from .subject_schedules import SCHEDULE_TYPES, SubjectScheduleKey, SubjectSchedules, label_from_interval

logger = structlog.get_logger(__name__)
SCHEDULE_REQUEST_TIMEOUT_SECONDS = 10


class ScheduleUnavailableError(Exception):
    pass


@frozen
class CheckSchedule:
    id: UUID
    interval: ScheduleInterval
    enabled: bool
    next_run_at: datetime | None
    last_run_at: datetime | None = None
    last_suite_run: UUID | None = None


@frozen
class ScheduleUpdateResult:
    before: CheckSchedule
    after: CheckSchedule


def schedule_key(team_id: int, subject_type: str, subject_uuid: str | UUID) -> SubjectScheduleKey:
    kind = SubjectType(subject_type)
    if kind not in SCHEDULE_TYPES:
        raise ValueError(f"A {kind} has no recurring check schedule")
    return SubjectScheduleKey(
        team_id=resolve_effective_team_id(team_id), subject_type=kind, subject_uuid=UUID(str(subject_uuid))
    )


def schedule_snapshot(key: SubjectScheduleKey, description: ScheduleDescription) -> CheckSchedule:
    schedule = description.schedule
    upcoming = description.info.next_action_times
    return CheckSchedule(
        id=key.id,
        interval=label_from_interval(schedule.spec.intervals[0].every),
        enabled=not schedule.state.paused,
        next_run_at=upcoming[0] if upcoming and not schedule.state.paused else None,
    )


async def _describe_schedule(schedules: SubjectSchedules, key: SubjectScheduleKey) -> CheckSchedule | None:
    async with asyncio.timeout(SCHEDULE_REQUEST_TIMEOUT_SECONDS):
        description = await schedules.describe(key)
    return schedule_snapshot(key, description) if description is not None else None


async def _update_schedule_with_snapshots(
    team_id: int,
    subject_type: str,
    subject_uuid: str | UUID,
    *,
    interval: str | None = None,
    enabled: bool | None = None,
) -> ScheduleUpdateResult:
    key = await sync_to_async(schedule_key)(team_id, subject_type, subject_uuid)
    try:
        async with asyncio.timeout(SCHEDULE_REQUEST_TIMEOUT_SECONDS):
            schedules = SubjectSchedules(await async_connect())
        before = await _describe_schedule(schedules, key)
        if before is None:
            raise ScheduleUnavailableError()
        async with asyncio.timeout(SCHEDULE_REQUEST_TIMEOUT_SECONDS):
            await schedules.update(key, interval=interval, enabled=enabled)
        after = await _describe_schedule(schedules, key)
        if after is None:
            raise ScheduleUnavailableError()
        return ScheduleUpdateResult(before=before, after=after)
    except ScheduleUnavailableError:
        raise
    except Exception as error:
        raise ScheduleUnavailableError() from error


@async_to_sync
async def provision_schedule(team_id: int, subject_type: str, subject_uuid: str) -> None:
    key = await sync_to_async(schedule_key)(team_id, subject_type, subject_uuid)
    try:
        async with asyncio.timeout(SCHEDULE_REQUEST_TIMEOUT_SECONDS):
            await SubjectSchedules(await async_connect()).ensure(key)
    except Exception:
        logger.exception(
            "data_quality_schedule_provision_failed",
            team_id=key.team_id,
            subject_type=str(key.subject_type),
            subject_uuid=str(key.subject_uuid),
        )


@async_to_sync
async def get_schedule(team_id: int, subject_type: str, subject_uuid: str | UUID) -> CheckSchedule | None:
    key = await sync_to_async(schedule_key)(team_id, subject_type, subject_uuid)
    try:
        async with asyncio.timeout(SCHEDULE_REQUEST_TIMEOUT_SECONDS):
            description = await SubjectSchedules(await async_connect()).describe(key)
        return schedule_snapshot(key, description) if description is not None else None
    except Exception as error:
        raise ScheduleUnavailableError() from error


@async_to_sync
async def get_schedules(
    team_id: int, subjects: Sequence[tuple[str, str | UUID]]
) -> dict[SubjectScheduleKey, CheckSchedule]:
    keys = [
        await sync_to_async(schedule_key)(team_id, subject_type, subject_uuid)
        for subject_type, subject_uuid in subjects
    ]
    if not keys:
        return {}
    try:
        async with asyncio.timeout(SCHEDULE_REQUEST_TIMEOUT_SECONDS):
            schedules = SubjectSchedules(await async_connect())
            snapshots = await asyncio.gather(*(_describe_schedule(schedules, key) for key in keys))
    except Exception as error:
        raise ScheduleUnavailableError() from error
    return {key: snapshot for key, snapshot in zip(keys, snapshots) if snapshot is not None}


@async_to_sync
async def set_schedule(
    team_id: int,
    subject_type: str,
    subject_uuid: str | UUID,
    *,
    interval: str | None = None,
    enabled: bool | None = None,
) -> None:
    key = await sync_to_async(schedule_key)(team_id, subject_type, subject_uuid)
    try:
        async with asyncio.timeout(SCHEDULE_REQUEST_TIMEOUT_SECONDS):
            await SubjectSchedules(await async_connect()).update(key, interval=interval, enabled=enabled)
    except Exception as error:
        raise ScheduleUnavailableError() from error


@async_to_sync
async def update_schedule_with_snapshots(
    team_id: int,
    subject_type: str,
    subject_uuid: str | UUID,
    *,
    interval: str | None = None,
    enabled: bool | None = None,
) -> ScheduleUpdateResult:
    return await _update_schedule_with_snapshots(
        team_id,
        subject_type,
        subject_uuid,
        interval=interval,
        enabled=enabled,
    )
