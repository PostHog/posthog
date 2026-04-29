"""Cron schedule registration for the weekly batched dmat workflows.

Two independent schedules cover the dmat lifecycle:

* ``weekly-dmat-compact`` fires the compaction workflow Saturday 00:00 UTC. Most weeks the
  workflow self-skips after a quick capacity check; when free columns drop below the
  threshold (~twice a year per the RFC) it allocates dense compaction targets, runs a
  single mutation to backfill them, then swaps slots onto the new column indexes.

* ``weekly-dmat-backfill`` fires the PENDING-allocation workflow Sunday 00:00 UTC. It picks
  up any PENDING slots, allocates fresh column indexes, runs the mutation, and activates
  them. Always at least 24h after the compaction firing so a long-running compaction
  mutation has finished (and its old columns are freed) before allocation looks at the
  free pool.

Register or refresh the schedules by calling
``create_or_update_weekly_dmat_backfill_schedule`` and
``create_or_update_weekly_dmat_compact_schedule`` from a management command or
initialization hook. Both are idempotent — running them twice is safe.
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
    CompactMaterializedColumnsInputs,
    CompactMaterializedColumnsWorkflow,
)
from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

# Sunday at 00:00 UTC — picked to be off-peak across regions and to coincide with the
# existing weekly maintenance window. The exact minute matters less than the day.
WEEKLY_DMAT_BACKFILL_CRON = "0 0 * * 0"
BACKFILL_SCHEDULE_ID = "weekly-dmat-backfill"

# Saturday at 00:00 UTC — 24h before the PENDING-allocation firing so any long-running
# compaction mutation has time to finish before allocation reads the free-column pool.
WEEKLY_DMAT_COMPACT_CRON = "0 0 * * 6"
COMPACT_SCHEDULE_ID = "weekly-dmat-compact"


async def create_or_update_weekly_dmat_backfill_schedule(client: Client) -> None:
    """Create or update the weekly PENDING-allocation cron schedule.

    Uses ScheduleOverlapPolicy.SKIP so a long-running mutation does not get a duplicate
    scheduled alongside it — the next firing is dropped instead of queued. The next
    week's cycle then picks up any slots still PENDING.
    """
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            BackfillMaterializedPropertiesBatchWorkflow.run,
            BackfillMaterializedPropertiesBatchInputs(),
            id=f"{BACKFILL_SCHEDULE_ID}-execution",
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            execution_timeout=dt.timedelta(hours=24),
        ),
        spec=ScheduleSpec(cron_expressions=[WEEKLY_DMAT_BACKFILL_CRON]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, BACKFILL_SCHEDULE_ID):
        await a_update_schedule(client, BACKFILL_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, BACKFILL_SCHEDULE_ID, schedule, trigger_immediately=False)


async def create_or_update_weekly_dmat_compact_schedule(client: Client) -> None:
    """Create or update the weekly compaction cron schedule.

    Uses ScheduleOverlapPolicy.SKIP for the same reason as the PENDING schedule. Compaction
    mutations are even longer (every READY slot's column gets backfilled), so SKIP rather
    than queueing is essential — a stalled compaction must not pile up duplicate firings.
    """
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            CompactMaterializedColumnsWorkflow.run,
            CompactMaterializedColumnsInputs(),
            id=f"{COMPACT_SCHEDULE_ID}-execution",
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            execution_timeout=dt.timedelta(hours=24),
        ),
        spec=ScheduleSpec(cron_expressions=[WEEKLY_DMAT_COMPACT_CRON]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, COMPACT_SCHEDULE_ID):
        await a_update_schedule(client, COMPACT_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, COMPACT_SCHEDULE_ID, schedule, trigger_immediately=False)
