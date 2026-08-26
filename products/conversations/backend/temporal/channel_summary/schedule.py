"""Schedule registration for the account channel summary coordinator."""

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

from products.conversations.backend.temporal.channel_summary.constants import COORDINATOR_INTERVAL_MINUTES
from products.conversations.backend.temporal.channel_summary.schemas import SummaryCoordinatorInput

CHANNEL_SUMMARY_COORDINATOR_SCHEDULE_ID = "account-channel-summary-coordinator-schedule"
CHANNEL_SUMMARY_COORDINATOR_WORKFLOW_NAME = "account-channel-summary-coordinator"


async def create_channel_summary_coordinator_schedule(client: Client) -> None:
    """Create or update the hourly schedule that drives the channel summary coordinator.

    Hourly (not daily) so each team's periods close on their own timezone's midnight;
    an account becomes due within an hour of its local period closing. Runs on the
    VIDEO_EXPORT_TASK_QUEUE like the support reply coordinator. ScheduleOverlapPolicy.SKIP
    guards against pathologically slow ticks.
    """
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            CHANNEL_SUMMARY_COORDINATOR_WORKFLOW_NAME,
            asdict(SummaryCoordinatorInput()),
            id=CHANNEL_SUMMARY_COORDINATOR_SCHEDULE_ID,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=COORDINATOR_INTERVAL_MINUTES))]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, CHANNEL_SUMMARY_COORDINATOR_SCHEDULE_ID):
        await a_update_schedule(client, CHANNEL_SUMMARY_COORDINATOR_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(
            client,
            CHANNEL_SUMMARY_COORDINATOR_SCHEDULE_ID,
            schedule,
            trigger_immediately=False,
        )
