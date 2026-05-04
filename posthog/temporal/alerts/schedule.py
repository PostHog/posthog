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

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

SCHEDULE_ID = "schedule-due-alert-checks-schedule"
INVESTIGATION_SAFETY_NET_SCHEDULE_ID = "run-investigation-safety-net-schedule"


async def create_schedule_due_alert_checks_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "schedule-due-alert-checks",
            id=SCHEDULE_ID,
            task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
            execution_timeout=dt.timedelta(minutes=10),
        ),
        spec=ScheduleSpec(cron_expressions=["*/2 * * * *"]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.ALLOW_ALL),
    )

    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)


async def create_run_investigation_safety_net_schedule(client: Client) -> None:
    """Investigation-gated alerts that stall past the grace period get force-notified by this sweep.

    Skip the run if the previous one is still in flight (SKIP overlap policy) — the
    sweep is idempotent and missing one tick is harmless because the next will pick
    up the same checks.
    """
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "run-investigation-safety-net",
            id=INVESTIGATION_SAFETY_NET_SCHEDULE_ID,
            task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
            execution_timeout=dt.timedelta(minutes=5),
        ),
        spec=ScheduleSpec(cron_expressions=["*/2 * * * *"]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, INVESTIGATION_SAFETY_NET_SCHEDULE_ID):
        await a_update_schedule(client, INVESTIGATION_SAFETY_NET_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, INVESTIGATION_SAFETY_NET_SCHEDULE_ID, schedule, trigger_immediately=False)
