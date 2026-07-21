"""Schedule registration for the ticket trends coordinator."""

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

from products.conversations.backend.temporal.trends.coordinator import (
    TRENDS_COORDINATOR_INTERVAL_MINUTES,
    TrendsCoordinatorInput,
)

TICKET_TRENDS_COORDINATOR_SCHEDULE_ID = "ticket-trends-coordinator-schedule"
TICKET_TRENDS_COORDINATOR_WORKFLOW_NAME = "ticket-trends-coordinator"


async def create_ticket_trends_coordinator_schedule(client: Client) -> None:
    """Create or update the schedule that drives the ticket trends coordinator.

    Runs on the VIDEO_EXPORT_TASK_QUEUE (shared with the other conversations
    workers). ScheduleOverlapPolicy.SKIP guards against pathologically slow ticks.
    """
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            TICKET_TRENDS_COORDINATOR_WORKFLOW_NAME,
            asdict(TrendsCoordinatorInput()),
            id=TICKET_TRENDS_COORDINATOR_SCHEDULE_ID,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            intervals=[ScheduleIntervalSpec(every=timedelta(minutes=TRENDS_COORDINATOR_INTERVAL_MINUTES))]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, TICKET_TRENDS_COORDINATOR_SCHEDULE_ID):
        await a_update_schedule(client, TICKET_TRENDS_COORDINATOR_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(
            client,
            TICKET_TRENDS_COORDINATOR_SCHEDULE_ID,
            schedule,
            trigger_immediately=False,
        )
