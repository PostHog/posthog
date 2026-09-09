from dataclasses import asdict

from django.conf import settings

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

from products.context_layer.backend.temporal.dreaming import DreamCoordinatorInput

CONTEXT_LAYER_DREAM_SCHEDULE_ID = "context-layer-dream-coordinator-schedule"


async def create_context_layer_dream_schedule(client: Client) -> None:
    """Nightly dreaming tick. SKIP is a guard against a pathologically slow
    tick; the coordinator only dispatches, so it normally finishes in seconds."""
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "context-layer-dream-coordinator",
            asdict(DreamCoordinatorInput()),
            id=CONTEXT_LAYER_DREAM_SCHEDULE_ID,
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        ),
        spec=ScheduleSpec(cron_expressions=["0 3 * * *"]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    if await a_schedule_exists(client, CONTEXT_LAYER_DREAM_SCHEDULE_ID):
        await a_update_schedule(client, CONTEXT_LAYER_DREAM_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, CONTEXT_LAYER_DREAM_SCHEDULE_ID, schedule, trigger_immediately=False)
