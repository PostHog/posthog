from collections import defaultdict

from temporalio import activity
from temporalio.service import RPCError, RPCStatusCode

from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.schedule import a_delete_schedule
from posthog.temporal.common.search_attributes import POSTHOG_SCHEDULE_TYPE_KEY

from products.data_catalog.backend.facade import api as data_catalog_facade

from ...facade.enums import SubjectType
from ...logic.metric_schedules import SCHEDULE_PREFIX, SCHEDULE_TYPE, MetricScheduleKey, MetricSchedules
from ...models import DataQualityCheck

RECONCILE_PAGE_SIZE = 100


@frozen
class ScheduleReconcileCursor:
    after_check_id: str | None = None
    cleanup: bool = False
    next_page_token: bytes | None = None
    done: bool = False


def _check_page(after_check_id: str | None) -> list[DataQualityCheck]:
    checks = DataQualityCheck.objects.unscoped().filter(subject_type=SubjectType.METRIC, metric__deleted=False)
    if after_check_id:
        checks = checks.filter(id__gt=after_check_id)
    return list(checks.only("id", "team_id", "metric_id").order_by("id")[:RECONCILE_PAGE_SIZE])


def _dead_schedules(schedule_ids: list[str]) -> list[str]:
    by_team: dict[int, list[MetricScheduleKey]] = defaultdict(list)
    for schedule_id in schedule_ids:
        if schedule_id.startswith(SCHEDULE_PREFIX):
            key = MetricScheduleKey.parse(schedule_id)
            by_team[key.team_id].append(key)
    dead: list[str] = []
    for team_id, keys in by_team.items():
        live = data_catalog_facade.metric_names_for_ids(team_id, [key.metric_id for key in keys])
        dead.extend(key.temporal_id for key in keys if key.metric_id not in live)
    return dead


@activity.defn
async def reconcile_metric_schedules_activity(cursor: ScheduleReconcileCursor) -> ScheduleReconcileCursor:
    client = await async_connect()
    if not cursor.cleanup:
        checks = await database_sync_to_async_pool(_check_page)(cursor.after_check_id)
        keys = {
            MetricScheduleKey(team_id=check.team_id, metric_id=check.metric_id) for check in checks if check.metric_id
        }
        for key in keys:
            await MetricSchedules(client).ensure(key)
            activity.heartbeat()
        return ScheduleReconcileCursor(
            after_check_id=str(checks[-1].id) if checks else None,
            cleanup=len(checks) < RECONCILE_PAGE_SIZE,
        )

    schedules = await client.list_schedules(
        query=f'{POSTHOG_SCHEDULE_TYPE_KEY.name} = "{SCHEDULE_TYPE}"',
        page_size=RECONCILE_PAGE_SIZE,
        next_page_token=cursor.next_page_token,
    )
    await schedules.fetch_next_page()
    schedule_ids = [schedule.id for schedule in schedules.current_page or []]
    dead = await database_sync_to_async_pool(_dead_schedules)(schedule_ids)
    for schedule_id in dead:
        try:
            await a_delete_schedule(client, schedule_id)
        except RPCError as error:
            if error.status != RPCStatusCode.NOT_FOUND:
                raise
        activity.heartbeat()
    return ScheduleReconcileCursor(
        cleanup=True, next_page_token=schedules.next_page_token, done=schedules.next_page_token is None
    )
