"""Schedule registration for the support reply coordinator."""

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

from products.conversations.backend.temporal.coordinator import COORDINATOR_INTERVAL_MINUTES, CoordinatorInput

SUPPORT_REPLY_COORDINATOR_SCHEDULE_ID = "support-reply-coordinator-schedule"
SUPPORT_REPLY_COORDINATOR_WORKFLOW_NAME = "support-reply-coordinator"


async def create_support_reply_coordinator_schedule(client: Client) -> None:
    """Create or update the schedule that drives the support reply coordinator.

    Runs on the VIDEO_EXPORT_TASK_QUEUE (shared with BK and signals workers).
    ScheduleOverlapPolicy.SKIP guards against pathologically slow ticks.
    """
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            SUPPORT_REPLY_COORDINATOR_WORKFLOW_NAME,
            asdict(CoordinatorInput()),
            id=SUPPORT_REPLY_COORDINATOR_SCHEDULE_ID,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=COORDINATOR_INTERVAL_MINUTES))]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, SUPPORT_REPLY_COORDINATOR_SCHEDULE_ID):
        await a_update_schedule(client, SUPPORT_REPLY_COORDINATOR_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(
            client,
            SUPPORT_REPLY_COORDINATOR_SCHEDULE_ID,
            schedule,
            trigger_immediately=False,
        )
