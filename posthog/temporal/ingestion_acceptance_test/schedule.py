"""Schedule for ingestion acceptance test workflow."""

import uuid
from datetime import timedelta

from django.conf import settings

from temporalio import common
from temporalio.client import Client, Schedule, ScheduleActionStartWorkflow, ScheduleIntervalSpec, ScheduleSpec

from posthog.temporal.common.schedule import a_create_schedule, a_delete_schedule, a_schedule_exists, a_update_schedule
from posthog.temporal.ingestion_acceptance_test.config import configured_lanes
from posthog.temporal.ingestion_acceptance_test.types import IngestionAcceptanceTestInput

SCHEDULE_ID = "ingestion-acceptance-test-schedule"
WORKFLOW_NAME = "ingestion-acceptance-test"


def _lane_schedule_id(lane: str) -> str:
    return f"ingestion-acceptance-test-{lane}-schedule"


async def create_ingestion_acceptance_test_schedule(client: Client) -> None:
    """Create or update the ingestion acceptance test schedules.

    Each schedule runs every 15 minutes to verify the ingestion pipeline is healthy.

    When INGESTION_ACCEPTANCE_TEST_LANES is set (e.g. "main,turbo"), one schedule
    is created per lane, each targeting that lane's ingestion routing. Lanes are
    declared per environment, so a region only schedules the lanes it lists.
    When unset, a single schedule using the flat env config is created (the
    pre-lane behavior).
    """
    lanes = configured_lanes()
    if lanes:
        # Retire the pre-lane schedule so "main" isn't tested by both it and the
        # main lane schedule after the lane cutover deploys.
        if await a_schedule_exists(client, SCHEDULE_ID):
            await a_delete_schedule(client, SCHEDULE_ID)
        for lane in lanes:
            await _upsert_schedule(client, _lane_schedule_id(lane), IngestionAcceptanceTestInput(lane=lane))
    else:
        await _upsert_schedule(client, SCHEDULE_ID, IngestionAcceptanceTestInput())


def _build_schedule(inputs: IngestionAcceptanceTestInput) -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME,
            inputs,
            id=str(uuid.uuid4()),
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            retry_policy=common.RetryPolicy(
                maximum_attempts=1,  # Don't retry - we want to know immediately if it fails
            ),
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=15))]),
    )


async def _upsert_schedule(client: Client, schedule_id: str, inputs: IngestionAcceptanceTestInput) -> None:
    schedule = _build_schedule(inputs)

    if await a_schedule_exists(client, schedule_id):
        await a_update_schedule(client, schedule_id, schedule)
    else:
        await a_create_schedule(client, schedule_id, schedule, trigger_immediately=False)
