import datetime as dt
from typing import TYPE_CHECKING

from django.conf import settings

from temporalio.client import Schedule, ScheduleActionStartWorkflow, ScheduleOverlapPolicy, SchedulePolicy, ScheduleSpec
from temporalio.common import RetryPolicy

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

if TYPE_CHECKING:
    from temporalio.client import Client

SCHEDULE_ID = "alerts-platform-check-due-schedule"
INVENTORY_SCHEDULE_ID = "alerts-platform-record-inventory-schedule"


async def create_alerts_platform_tick_schedule(client: "Client") -> None:
    await _create_or_update(
        client,
        SCHEDULE_ID,
        "alerts-platform-orchestrate",
        execution_timeout=dt.timedelta(seconds=50),
    )


async def create_alerts_platform_inventory_schedule(client: "Client") -> None:
    await _create_or_update(
        client,
        INVENTORY_SCHEDULE_ID,
        "alerts-platform-record-inventory",
        execution_timeout=dt.timedelta(seconds=30),
    )


async def _create_or_update(
    client: "Client", schedule_id: str, workflow_name: str, *, execution_timeout: dt.timedelta
) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            workflow_name,
            {},
            id=schedule_id,
            task_queue=settings.ALERTS_PLATFORM_SHARED_ORCHESTRATION_TASK_QUEUE,
            execution_timeout=execution_timeout,
            retry_policy=RetryPolicy(maximum_attempts=1),
        ),
        spec=ScheduleSpec(cron_expressions=["* * * * *"]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=dt.timedelta(minutes=1)),
    )

    if await a_schedule_exists(client, schedule_id):
        description = await client.get_schedule_handle(schedule_id).describe()
        # nosemgrep: insight-alert-state-direct-mutation (Temporal schedule state, not an alert)
        schedule.state = description.schedule.state
        await a_update_schedule(client, schedule_id, schedule)
    else:
        await a_create_schedule(client, schedule_id, schedule, trigger_immediately=False)
