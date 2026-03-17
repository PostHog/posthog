import asyncio
import datetime as dt

import pytest

import temporalio.client

from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse
from posthog.temporal.tests.utils.models import acreate_batch_export, adelete_batch_export


async def wait_for_workflows(
    temporal_client: temporalio.client.Client,
    schedule_id: str,
    expected_count: int,
    timeout: int = 30,
) -> list[temporalio.client.WorkflowExecution]:
    """Wait for workflows to be queryable and return them."""
    query = f'TemporalScheduledById="{schedule_id}" order by StartTime asc'
    workflows: list[temporalio.client.WorkflowExecution] = []
    waited = 0

    while len(workflows) < expected_count:
        waited += 1
        if waited > timeout:
            raise TimeoutError(
                f"Timed-out waiting for workflows for schedule {schedule_id} to be query-able. "
                f"Found {len(workflows)} workflows, expected {expected_count}"
            )

        await asyncio.sleep(1)
        workflows = [workflow async for workflow in temporal_client.list_workflows(query=query)]

    assert len(workflows) == expected_count
    return workflows


async def assert_backfill_details_in_workflow_events(
    temporal_client: temporalio.client.Client,
    workflows: list[temporalio.client.WorkflowExecution],
    expected_backfill_id: str | None = None,
    expected_start_at: str | None = None,
    expected_end_at: str | None = None,
    expected_is_earliest_backfill: bool | None = None,
) -> list[str]:
    """Assert backfill details are correctly set in workflow events."""
    backfill_ids = []
    for workflow in workflows:
        handle = temporal_client.get_workflow_handle(workflow.id)
        history = await handle.fetch_history()

        for event in history.events:
            if event.event_type == 1:  # EVENT_TYPE_WORKFLOW_EXECUTION_STARTED
                payloads = event.workflow_execution_started_event_attributes.input.payloads
            elif event.event_type == 10:  # EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
                payloads = event.activity_task_scheduled_event_attributes.input.payloads
            else:
                continue

            args = await workflow.data_converter.decode(payloads)
            backfill_details = args[0]["backfill_details"]
            if expected_backfill_id is not None:
                assert backfill_details["backfill_id"] == expected_backfill_id
            if expected_start_at is not None:
                assert backfill_details["start_at"] == expected_start_at
            elif "start_at" in backfill_details:
                assert backfill_details["start_at"] is None
            if expected_end_at is not None:
                assert backfill_details["end_at"] == expected_end_at
            elif "end_at" in backfill_details:
                assert backfill_details["end_at"] is None
            if expected_is_earliest_backfill is not None:
                assert backfill_details["is_earliest_backfill"] == expected_is_earliest_backfill
            backfill_ids.append(backfill_details["backfill_id"])

    return backfill_ids


@pytest.fixture
async def temporal_schedule_hourly(temporal_client, ateam):
    """Manage a test Temporal Schedule with interval 'hour'."""
    batch_export = await acreate_batch_export(
        team_id=ateam.pk,
        name="no-op-export-hourly",
        destination_data={
            "type": "NoOp",
            "config": {},
        },
        interval="hour",
        paused=True,
    )

    handle = temporal_client.get_schedule_handle(str(batch_export.id))
    yield handle

    await adelete_batch_export(batch_export, temporal_client)


@pytest.fixture
def generate_events(clickhouse_client, ateam):
    """Factory fixture to generate test events in ClickHouse with sensible defaults.

    Returns a coroutine function that can be awaited with custom parameters.
    Defaults: table="sharded_events", end_time=start_time+1h, inserted_at=start_time.
    """

    async def _generate(
        start_time: dt.datetime,
        end_time: dt.datetime | None = None,
        inserted_at: dt.datetime | None = None,
        count: int = 10,
        event_name: str = "test-event",
        count_outside_range: int = 0,
        count_other_team: int = 0,
    ):
        await generate_test_events_in_clickhouse(
            client=clickhouse_client,
            team_id=ateam.pk,
            start_time=start_time,
            end_time=end_time or start_time + dt.timedelta(hours=1),
            count=count,
            inserted_at=inserted_at or start_time,
            table="sharded_events",
            event_name=event_name,
            count_outside_range=count_outside_range,
            count_other_team=count_other_team,
        )

    return _generate
