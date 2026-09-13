from __future__ import annotations

from dataclasses import asdict
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

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

from products.conversations.backend.temporal.patterns.constants import COORDINATOR_INTERVAL_MINUTES
from products.conversations.backend.temporal.patterns.schemas import PatternCoordinatorInput

TICKET_PATTERN_COORDINATOR_SCHEDULE_ID = "ticket-patterns-coordinator-schedule"
TICKET_PATTERN_COORDINATOR_WORKFLOW_NAME = "ticket-patterns-coordinator"


async def create_ticket_pattern_coordinator_schedule(client: Client) -> None:
    """Runs on the VIDEO_EXPORT_TASK_QUEUE like the other conversations coordinators. The execution
    timeout matches the interval so a tick that burns its retry budget under SKIP cannot starve the
    ticks after it."""
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            TICKET_PATTERN_COORDINATOR_WORKFLOW_NAME,
            asdict(PatternCoordinatorInput()),
            id=TICKET_PATTERN_COORDINATOR_SCHEDULE_ID,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            execution_timeout=timedelta(minutes=COORDINATOR_INTERVAL_MINUTES),
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=COORDINATOR_INTERVAL_MINUTES))]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, TICKET_PATTERN_COORDINATOR_SCHEDULE_ID):
        await a_update_schedule(client, TICKET_PATTERN_COORDINATOR_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, TICKET_PATTERN_COORDINATOR_SCHEDULE_ID, schedule, trigger_immediately=False)
