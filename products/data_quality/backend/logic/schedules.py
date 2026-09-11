import asyncio
from datetime import datetime
from uuid import UUID

import structlog
from asgiref.sync import async_to_sync, sync_to_async

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.temporal.common.client import async_connect

from ..facade.enums import ScheduleInterval, SubjectType
from .metric_schedules import MetricScheduleKey, MetricSchedules, label_from_interval

logger = structlog.get_logger(__name__)
SCHEDULE_REQUEST_TIMEOUT_SECONDS = 10


class ScheduleUnavailableError(Exception):
    pass


@frozen
class MetricCheckSchedule:
    id: UUID
    interval: ScheduleInterval
    enabled: bool
    next_run_at: datetime | None
    last_run_at: datetime | None = None
    last_suite_run: UUID | None = None


def schedule_key(team_id: int, subject_type: str, subject_uuid: str | UUID) -> MetricScheduleKey:
    if subject_type != SubjectType.METRIC:
        raise ValueError("Only metrics support recurring check schedules")
    return MetricScheduleKey(team_id=resolve_effective_team_id(team_id), metric_id=UUID(str(subject_uuid)))


@async_to_sync
async def provision_metric_schedule(team_id: int, metric_id: str) -> None:
    key = await sync_to_async(schedule_key)(team_id, SubjectType.METRIC, metric_id)
    try:
        async with asyncio.timeout(SCHEDULE_REQUEST_TIMEOUT_SECONDS):
            await MetricSchedules(await async_connect()).ensure(key)
    except Exception:
        logger.exception("data_quality_schedule_provision_failed", team_id=key.team_id, metric_id=str(key.metric_id))


@async_to_sync
async def get_schedule(team_id: int, subject_type: str, subject_uuid: str | UUID) -> MetricCheckSchedule | None:
    key = await sync_to_async(schedule_key)(team_id, subject_type, subject_uuid)
    try:
        async with asyncio.timeout(SCHEDULE_REQUEST_TIMEOUT_SECONDS):
            description = await MetricSchedules(await async_connect()).describe(key)
        if description is None:
            return None
        schedule = description.schedule
        interval = label_from_interval(schedule.spec.intervals[0].every)
        upcoming = description.info.next_action_times
        return MetricCheckSchedule(
            id=key.id,
            interval=interval,
            enabled=not schedule.state.paused,
            next_run_at=upcoming[0] if upcoming and not schedule.state.paused else None,
        )
    except Exception as error:
        raise ScheduleUnavailableError() from error


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
            await MetricSchedules(await async_connect()).update(key, interval=interval, enabled=enabled)
    except Exception as error:
        raise ScheduleUnavailableError() from error
