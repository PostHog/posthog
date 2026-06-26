from datetime import timedelta

from django.conf import settings

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from posthog.temporal.ai.checkpoint_compaction.types import CompactionSweepInput
from posthog.temporal.ai.checkpoint_compaction.workflow import CheckpointCompactionWorkflow
from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

CHECKPOINT_COMPACTION_SCHEDULE_ID = "checkpoint-compaction-sweep-schedule"


async def create_checkpoint_compaction_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            CheckpointCompactionWorkflow.get_name(),
            CompactionSweepInput().model_dump(),
            id=CHECKPOINT_COMPACTION_SCHEDULE_ID,
            task_queue=settings.MAX_AI_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(days=1))]),
        # A sweep can continue-as-new for a while; never let a slow run overlap the next day's.
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, CHECKPOINT_COMPACTION_SCHEDULE_ID):
        await a_update_schedule(client, CHECKPOINT_COMPACTION_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, CHECKPOINT_COMPACTION_SCHEDULE_ID, schedule, trigger_immediately=False)
