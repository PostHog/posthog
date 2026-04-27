"""Cron schedule registration for the weekly batched dmat backfill workflow.

Register or refresh the schedule by calling ``create_or_update_weekly_dmat_backfill_schedule``
from a management command or initialization hook. The schedule is idempotent — running it
twice is safe.
"""

import datetime as dt

from django.conf import settings

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from posthog.temporal.backfill_materialized_property.workflows import (
    BackfillMaterializedPropertiesBatchInputs,
    BackfillMaterializedPropertiesBatchWorkflow,
)
from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

# Sunday at 00:00 UTC — picked to be off-peak across regions and to coincide with the
# existing weekly maintenance window. The exact minute matters less than the day.
WEEKLY_DMAT_BACKFILL_CRON = "0 0 * * 0"
SCHEDULE_ID = "weekly-dmat-backfill"


async def create_or_update_weekly_dmat_backfill_schedule(client: Client) -> None:
    """Create or update the weekly cron schedule.

    Uses ScheduleOverlapPolicy.SKIP so a long-running mutation does not get a duplicate
    scheduled alongside it — the next firing is dropped instead of queued. The next
    week's cycle then picks up any slots still PENDING.
    """
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            BackfillMaterializedPropertiesBatchWorkflow.run,
            BackfillMaterializedPropertiesBatchInputs(),
            id=f"{SCHEDULE_ID}-execution",
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            execution_timeout=dt.timedelta(hours=24),
        ),
        spec=ScheduleSpec(cron_expressions=[WEEKLY_DMAT_BACKFILL_CRON]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
