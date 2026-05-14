"""Temporal schedule wiring for nightly social referral status checks."""

from dataclasses import asdict

from django.conf import settings

from temporalio import common
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule
from posthog.temporal.social_referral_status.types import SocialReferralStatusInputs

SCHEDULE_ID = "social-referral-status-schedule"
WORKFLOW_NAME = "social-referral-status"


async def create_social_referral_status_schedule(client: Client) -> None:
    """Run referral status workflow nightly at midnight UTC with SKIP overlap."""
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME,
            asdict(SocialReferralStatusInputs()),
            id=SCHEDULE_ID,
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            retry_policy=common.RetryPolicy(maximum_attempts=3),
        ),
        spec=ScheduleSpec(cron_expressions=["0 0 * * *"]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
