import asyncio
from collections import defaultdict

from temporalio import activity
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.schedule import a_delete_schedule
from posthog.temporal.common.search_attributes import POSTHOG_SCHEDULE_TYPE_KEY

from products.data_catalog.backend.facade import api as data_catalog_facade

from ...facade.enums import SubjectType
from ...logic.subject_schedules import SCHEDULE_TYPES, SubjectScheduleKey, SubjectSchedules
from ...models import DataQualityCheck

RECONCILE_PAGE_SIZE = 100
RECONCILE_CONCURRENCY_LIMIT = 10


@frozen
class ScheduleReconcileCursor:
    after_check_id: str | None = None
    cleanup: bool = False
    next_page_token: bytes | None = None
    done: bool = False


SCHEDULED_SUBJECT_TYPES = tuple(SCHEDULE_TYPES)
SCHEDULE_TYPE_QUERY = " OR ".join(
    f'{POSTHOG_SCHEDULE_TYPE_KEY.name} = "{schedule_type}"' for schedule_type in SCHEDULE_TYPES.values()
)


def _check_page(after_check_id: str | None) -> list[DataQualityCheck]:
    checks = DataQualityCheck.objects.unscoped().filter(subject_type__in=SCHEDULED_SUBJECT_TYPES)
    checks = checks.exclude(metric__deleted=True)
    if after_check_id:
        checks = checks.filter(id__gt=after_check_id)
    return list(
        checks.only(
            "id", "team_id", "subject_type", "metric_id", "saved_query_id", "table_id", "posthog_table"
        ).order_by("id")[:RECONCILE_PAGE_SIZE]
    )


def _dead_schedules(schedule_ids: list[str]) -> list[str]:
    by_team: dict[int, list[SubjectScheduleKey]] = defaultdict(list)
    for schedule_id in schedule_ids:
        try:
            key = SubjectScheduleKey.parse(schedule_id)
        except ValueError:
            continue
        by_team[key.team_id].append(key)
    dead: list[str] = []
    for team_id, keys in by_team.items():
        metric_keys = [key for key in keys if key.subject_type == SubjectType.METRIC]
        live = data_catalog_facade.metric_names_for_ids(team_id, [key.subject_uuid for key in metric_keys])
        dead.extend(key.temporal_id for key in metric_keys if key.subject_uuid not in live)
    return dead


@activity.defn
async def reconcile_metric_schedules_activity(cursor: ScheduleReconcileCursor) -> ScheduleReconcileCursor:
    client = await async_connect()
    schedules = SubjectSchedules(client)
    semaphore = asyncio.Semaphore(RECONCILE_CONCURRENCY_LIMIT)
    if not cursor.cleanup:
        checks = await database_sync_to_async_pool(_check_page)(cursor.after_check_id)
        keys = list(
            dict.fromkeys(
                SubjectScheduleKey(
                    team_id=check.team_id,
                    subject_type=SubjectType(check.subject_type),
                    subject_uuid=check.subject_uuid,
                )
                for check in checks
                if check.subject_uuid
            )
        )
        async with asyncio.TaskGroup() as tasks:
            for key in keys:
                tasks.create_task(_ensure_schedule(schedules, key, semaphore))
        return ScheduleReconcileCursor(
            after_check_id=str(checks[-1].id) if checks else None,
            cleanup=len(checks) < RECONCILE_PAGE_SIZE,
        )

    schedule_page = await client.list_schedules(
        query=SCHEDULE_TYPE_QUERY,
        page_size=RECONCILE_PAGE_SIZE,
        next_page_token=cursor.next_page_token,
    )
    await schedule_page.fetch_next_page()
    schedule_ids = [schedule.id for schedule in schedule_page.current_page or []]
    dead = await database_sync_to_async_pool(_dead_schedules)(schedule_ids)
    async with asyncio.TaskGroup() as tasks:
        for schedule_id in dead:
            tasks.create_task(_delete_schedule(client, schedule_id, semaphore))
    return ScheduleReconcileCursor(
        cleanup=True, next_page_token=schedule_page.next_page_token, done=schedule_page.next_page_token is None
    )


async def _ensure_schedule(schedules: SubjectSchedules, key: SubjectScheduleKey, semaphore: asyncio.Semaphore) -> None:
    async with semaphore:
        await schedules.ensure(key)
        activity.heartbeat()


async def _delete_schedule(client: Client, schedule_id: str, semaphore: asyncio.Semaphore) -> None:
    async with semaphore:
        try:
            await a_delete_schedule(client, schedule_id)
        except RPCError as error:
            if error.status != RPCStatusCode.NOT_FOUND:
                raise
        activity.heartbeat()
