"""Cron schedule for the weekly pending-review digest, registered on the weekly digest queue."""

from datetime import timedelta

from django.conf import settings

from temporalio import common
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleCalendarSpec,
    ScheduleRange,
    ScheduleSpec,
)

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

from .weekly_digest.types import DataCatalogWeeklyDigestInput
from .weekly_digest.workflows import WORKFLOW_NAME

SCHEDULE_ID = "data-catalog-weekly-digest-schedule"


async def create_data_catalog_weekly_digest_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME,
            # dry_run defaults to True as a manual-run fail-safe; the schedule is the one
            # caller that must send for real.
            DataCatalogWeeklyDigestInput(dry_run=False),
            id=SCHEDULE_ID,
            task_queue=settings.WEEKLY_DIGEST_TASK_QUEUE,
            retry_policy=common.RetryPolicy(maximum_attempts=1),
            # Overlap defaults to SKIP, so a run that never closes drops every later Tuesday and
            # the digest stops for good. Nothing inside the workflow caps total duration: the page
            # loop is unbounded and the activities set only start_to_close. A day is far above any
            # expected run and far below the week, so a wedged run dies before the next one is due.
            execution_timeout=timedelta(hours=24),
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    comment="Weekly at Tuesday 9 AM UTC",
                    hour=[ScheduleRange(start=9, end=9)],
                    day_of_week=[ScheduleRange(start=2, end=2)],
                )
            ],
            time_zone_name="UTC",
        ),
    )

    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
