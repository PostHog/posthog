"""Schedule registration for the logs volume tick workflow."""

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

from products.logs.backend.facade.temporal import (
    VOLUME_TICK_SCHEDULE_CRON,
    VOLUME_TICK_SCHEDULE_ID,
    VOLUME_TICK_WORKFLOW_NAME,
    VolumeTickInput,
)


async def create_logs_volume_tick_schedule(client: Client) -> None:
    """Create or update the logs volume tick schedule."""
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            VOLUME_TICK_WORKFLOW_NAME,
            asdict(VolumeTickInput()),
            id=VOLUME_TICK_SCHEDULE_ID,
            # Rides the logs-alerting queue so the skeleton needs no new worker
            # deployment; split to a dedicated queue when the rollup writer's
            # resource profile justifies one.
            task_queue=settings.LOGS_ALERTING_TASK_QUEUE,
        ),
        spec=ScheduleSpec(cron_expressions=[VOLUME_TICK_SCHEDULE_CRON]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, VOLUME_TICK_SCHEDULE_ID):
        await a_update_schedule(client, VOLUME_TICK_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, VOLUME_TICK_SCHEDULE_ID, schedule, trigger_immediately=False)
