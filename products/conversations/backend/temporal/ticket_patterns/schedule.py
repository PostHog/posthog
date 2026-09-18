"""Schedule registration for the ticket pattern coordinator."""

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

from products.conversations.backend.temporal.ticket_patterns.constants import COORDINATOR_INTERVAL_MINUTES
from products.conversations.backend.temporal.ticket_patterns.schemas import PatternsCoordinatorInput

TICKET_PATTERNS_COORDINATOR_SCHEDULE_ID = "ticket-patterns-coordinator-schedule"
TICKET_PATTERNS_COORDINATOR_WORKFLOW_NAME = "ticket-patterns-coordinator"


async def create_ticket_patterns_coordinator_schedule(client: Client) -> None:
    """Create or update the schedule that drives ticket pattern detection.

    Runs on the VIDEO_EXPORT_TASK_QUEUE like the other conversations coordinators.
    ScheduleOverlapPolicy.SKIP guards against a tick that outlives its interval; the next tick
    reads the same window anyway, so a skipped one loses nothing.
    """
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            TICKET_PATTERNS_COORDINATOR_WORKFLOW_NAME,
            asdict(PatternsCoordinatorInput()),
            id=TICKET_PATTERNS_COORDINATOR_SCHEDULE_ID,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=COORDINATOR_INTERVAL_MINUTES))]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, TICKET_PATTERNS_COORDINATOR_SCHEDULE_ID):
        await a_update_schedule(client, TICKET_PATTERNS_COORDINATOR_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(
            client,
            TICKET_PATTERNS_COORDINATOR_SCHEDULE_ID,
            schedule,
            trigger_immediately=False,
        )
