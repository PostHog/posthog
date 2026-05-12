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

SCHEDULE_ID = "schedule-due-watched-questions-schedule"


async def create_schedule_due_watched_questions_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "schedule-due-watched-questions",
            id=SCHEDULE_ID,
            task_queue=settings.MAX_AI_TASK_QUEUE,
            execution_timeout=dt.timedelta(minutes=30),
        ),
        # Hourly at :07 — offset from alerts (every 2 min) and subscriptions (:55).
        spec=ScheduleSpec(cron_expressions=["7 * * * *"]),
        # SKIP — re-running while a previous tick is still in flight only stresses Postgres;
        # the next tick will pick up the same due questions.
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
