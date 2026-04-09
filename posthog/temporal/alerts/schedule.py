"""Schedule registration for the alert check coordinator workflow."""

import datetime as dt
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

from posthog.temporal.alerts.types import ScheduleAllAlertChecksWorkflowInputs
from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

SCHEDULE_ID = "schedule-all-alert-checks-schedule"


async def create_schedule_all_alert_checks_schedule(client: Client) -> None:
    """Create or update the schedule for the ScheduleAllAlertChecksWorkflow.

    Runs every 2 minutes to match the existing Celery beat cadence at
    posthog/tasks/scheduled.py:475-479. We use a cron expression rather
    than `ScheduleIntervalSpec` so the ticks align to wall-clock minutes
    (:00, :02, :04, ...) — the same alignment Celery's `crontab(minute="*/2")`
    gives today.

    ALLOW_ALL overlap is safe because child workflows use deterministic IDs
    (`check-alert-{alert_id}`) — a still-running child rejects the
    duplicate start with WorkflowAlreadyStartedError.

    `execution_timeout` on the coordinator caps a stuck dispatch cycle.
    The coordinator does only enumeration + child workflow starts;
    expected runtime is seconds. 10 minutes is a generous safety bound.
    """
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "schedule-all-alert-checks",
            asdict(ScheduleAllAlertChecksWorkflowInputs()),
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
