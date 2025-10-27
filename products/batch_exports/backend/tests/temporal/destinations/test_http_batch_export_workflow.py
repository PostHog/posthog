import json
import asyncio
import datetime as dt
from random import randint
from uuid import uuid4

import pytest
import unittest.mock

from django.conf import settings
from django.test import override_settings

from aioresponses import aioresponses
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.common.clickhouse import ClickHouseClient
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse
from posthog.temporal.tests.utils.models import acreate_batch_export, adelete_batch_export, afetch_batch_export_runs

from products.batch_exports.backend.temporal.batch_exports import (
    BackfillDetails,
    finish_batch_export_run,
    iter_records,
    start_batch_export_run,
)
from products.batch_exports.backend.temporal.destinations.http_batch_export import (
    HeartbeatDetails,
    HttpBatchExportInputs,
    HttpBatchExportWorkflow,
    HttpInsertInputs,
    RetryableResponseError,
    http_default_fields,
    insert_into_http_activity,
)
from products.batch_exports.backend.tests.temporal.utils.workflow import mocked_start_batch_export_run

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.django_db,
]

TEST_URL = "http://example.com/batch"
TEST_TOKEN = "abcdef123456"


@pytest.fixture
def http_config():
    return {
        "url": TEST_URL,
        "token": TEST_TOKEN,
    }


class MockServer:
    def __init__(self):
        self.records = []

    def post(self, url, data, **kwargs):
        data = json.loads(data.read())
        assert data["historical_migration"]
        assert data["api_key"] == TEST_TOKEN
        self.records.extend(data["batch"])


async def assert_clickhouse_records_in_mock_server(
    mock_server,
    clickhouse_client: ClickHouseClient,
    team_id: int,
    data_interval_start: dt.datetime,
    data_interval_end: dt.datetime,
    exclude_events: list[str] | None = None,
    include_events: list[str] | None = None,
    backfill_details: BackfillDetails | None = None,
):
    """Assert expected records are written to a MockServer instance."""
    posted_records = mock_server.records

    schema_column_names = [field["alias"] for field in http_default_fields()]

    expected_records = []
    for records in iter_records(
        client=clickhouse_client,
        team_id=team_id,
        interval_start=data_interval_start.isoformat(),
        interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        include_events=include_events,
        fields=http_default_fields(),
        extra_query_parameters=None,
        backfill_details=backfill_details,
    ):
        for record in records.select(schema_column_names).to_pylist():
            expected_record = {}

            for k, v in record.items():
                if k == "properties":
                    expected_record[k] = json.loads(v) if v else {}
                elif isinstance(v, dt.datetime):
                    expected_record[k] = v.replace(tzinfo=dt.UTC).isoformat()
                else:
                    expected_record[k] = v

            expected_record["properties"]["$geoip_disable"] = True

            expected_record.pop("_inserted_at")
            elements_chain = expected_record.pop("elements_chain", None)
            if expected_record["event"] == "$autocapture" and elements_chain is not None:
                expected_record["properties"]["$elements_chain"] = elements_chain

            expected_records.append(expected_record)

    inserted_column_names = list(posted_records[0].keys()).sort()
    expected_column_names = list(expected_records[0].keys()).sort()

    assert inserted_column_names == expected_column_names
    assert posted_records[0] == expected_records[0]
    assert posted_records == expected_records


@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
async def test_insert_into_http_activity_inserts_data_into_http_endpoint(
    clickhouse_client, activity_environment, http_config, exclude_events
):
    """Test that the insert_into_http_activity function POSTs data to an HTTP Endpoint.

    We use the generate_test_events_in_clickhouse function to generate several sets
    of events. Some of these sets are expected to be exported, and others not. Expected
    events are those that:
    * Are created for the team_id of the batch export.
    * Are created in the date range of the batch export.
    * Are not duplicates of other events that are in the same batch.
    * Do not have an event name contained in the batch export's exclude_events.
    """
    data_interval_start = dt.datetime(2023, 4, 20, 14, 0, 0, tzinfo=dt.UTC)
    data_interval_end = dt.datetime(2023, 4, 25, 15, 0, 0, tzinfo=dt.UTC)

    # Generate a random team id integer. There's still a chance of a collision,
    # but it's very small.
    team_id = randint(1, 1000000)

    await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=team_id,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=10000,
        count_outside_range=10,
        count_other_team=10,
        duplicate=True,
        properties={"$browser": "Chrome", "$os": "Mac OS X"},
        person_properties={"utm_medium": "referral", "$initial_os": "Linux"},
        table="sharded_events",
    )

    await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=team_id,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=5,
        count_outside_range=0,
        count_other_team=0,
        properties=None,
        person_properties=None,
        event_name="test-no-prop-{i}",
        table="sharded_events",
    )

    if exclude_events:
        for event_name in exclude_events:
            await generate_test_events_in_clickhouse(
                client=clickhouse_client,
                team_id=team_id,
                start_time=data_interval_start,
                end_time=data_interval_end,
                count=5,
                count_outside_range=0,
                count_other_team=0,
                event_name=event_name,
                table="sharded_events",
            )

    insert_inputs = HttpInsertInputs(
        team_id=team_id,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        batch_export_schema=None,
        backfill_details=BackfillDetails(
            backfill_id=None,
            start_at=data_interval_start.isoformat(),
            end_at=data_interval_end.isoformat(),
        ),
        **http_config,
    )

    mock_server = MockServer()
    with (
        aioresponses(passthrough=[settings.CLICKHOUSE_HTTP_URL]) as m,
        override_settings(BATCH_EXPORT_HTTP_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2),
    ):
        m.post(TEST_URL, status=200, callback=mock_server.post, repeat=True)
        await activity_environment.run(insert_into_http_activity, insert_inputs)

    await assert_clickhouse_records_in_mock_server(
        mock_server=mock_server,
        clickhouse_client=clickhouse_client,
        team_id=team_id,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        exclude_events=exclude_events,
        backfill_details=insert_inputs.backfill_details,
    )


async def test_insert_into_http_activity_throws_on_bad_http_status(
    clickhouse_client, activity_environment, http_config, exclude_events
):
    """Test that the insert_into_http_activity function throws on status >= 400"""
    data_interval_start = dt.datetime(2023, 4, 20, 14, 0, 0, tzinfo=dt.UTC)
    data_interval_end = dt.datetime(2023, 4, 25, 15, 0, 0, tzinfo=dt.UTC)

    # Generate a random team id integer. There's still a chance of a collision,
    # but it's very small.
    team_id = randint(1, 1000000)

    await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=team_id,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=1,
        count_outside_range=10,
        count_other_team=10,
        duplicate=True,
        properties={"$browser": "Chrome", "$os": "Mac OS X"},
        person_properties={"utm_medium": "referral", "$initial_os": "Linux"},
        table="sharded_events",
    )

    insert_inputs = HttpInsertInputs(
        team_id=team_id,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        batch_export_schema=None,
        backfill_details=BackfillDetails(
            backfill_id=None,
            start_at=data_interval_start.isoformat(),
            end_at=data_interval_end.isoformat(),
        ),
        **http_config,
    )

    # this is a non-retryable error, so should not raise an exception but should return a BatchExportResult with the error
    with (
        aioresponses(passthrough=[settings.CLICKHOUSE_HTTP_URL]) as m,
        override_settings(BATCH_EXPORT_HTTP_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2),
    ):
        m.post(TEST_URL, status=400, body="A useful error message", repeat=True)
        result = await activity_environment.run(insert_into_http_activity, insert_inputs)
        assert result.error is not None
        assert result.error.type == "NonRetryableResponseError"
        assert result.error.message == "NonRetryableResponseError (status: 400): A useful error message"
        assert (
            result.error_repr
            == "NonRetryableResponseError: NonRetryableResponseError (status: 400): A useful error message"
        )

    with (
        aioresponses(passthrough=[settings.CLICKHOUSE_HTTP_URL]) as m,
        override_settings(BATCH_EXPORT_HTTP_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2),
    ):
        m.post(TEST_URL, status=429, repeat=True)
        with pytest.raises(RetryableResponseError):
            await activity_environment.run(insert_into_http_activity, insert_inputs)

    with (
        aioresponses(passthrough=[settings.CLICKHOUSE_HTTP_URL]) as m,
        override_settings(BATCH_EXPORT_HTTP_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2),
    ):
        m.post(TEST_URL, status=500, repeat=True)
        with pytest.raises(RetryableResponseError):
            await activity_environment.run(insert_into_http_activity, insert_inputs)


@pytest.fixture
async def http_batch_export(ateam, http_config, interval, exclude_events, temporal_client):
    destination_data = {
        "type": "HTTP",
        "config": {**http_config, "exclude_events": exclude_events},
    }
    batch_export_data = {
        "name": "my-production-http-export",
        "destination": destination_data,
        "interval": interval,
    }

    batch_export = await acreate_batch_export(
        team_id=ateam.pk,
        name=batch_export_data["name"],
        destination_data=batch_export_data["destination"],
        interval=batch_export_data["interval"],
    )

    yield batch_export

    await adelete_batch_export(batch_export, temporal_client)


@pytest.mark.parametrize("interval", ["hour", "day"], indirect=True)
@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
async def test_http_export_workflow(
    clickhouse_client,
    http_batch_export,
    interval,
    exclude_events,
    ateam,
    batch_export_schema,
):
    """Test HTTP Export Workflow end-to-end by using a mock server.

    The workflow should update the batch export run status to completed and produce the expected
    records to the mock server.
    """
    data_interval_end = dt.datetime.now(tz=dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    data_interval_start = data_interval_end - http_batch_export.interval_time_delta

    await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=ateam.pk,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=100,
        count_outside_range=10,
        count_other_team=10,
        duplicate=True,
        properties={"$browser": "Chrome", "$os": "Mac OS X"},
        person_properties={"utm_medium": "referral", "$initial_os": "Linux"},
    )

    if exclude_events:
        for event_name in exclude_events:
            await generate_test_events_in_clickhouse(
                client=clickhouse_client,
                team_id=ateam.pk,
                start_time=data_interval_start,
                end_time=data_interval_end,
                count=5,
                count_outside_range=0,
                count_other_team=0,
                event_name=event_name,
            )

    workflow_id = str(uuid4())
    inputs = HttpBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(http_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_schema=batch_export_schema,
        **http_batch_export.destination.config,
    )

    mock_server = MockServer()
    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[HttpBatchExportWorkflow],
            activities=[
                start_batch_export_run,
                insert_into_http_activity,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with (
                aioresponses(passthrough=[settings.CLICKHOUSE_HTTP_URL]) as m,
                override_settings(BATCH_EXPORT_HTTP_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2),
            ):
                m.post(TEST_URL, status=200, callback=mock_server.post, repeat=True)

                await activity_environment.client.execute_workflow(
                    HttpBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=dt.timedelta(seconds=10),
                )

    runs = await afetch_batch_export_runs(batch_export_id=http_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"
    assert run.records_completed == 100

    await assert_clickhouse_records_in_mock_server(
        mock_server=mock_server,
        clickhouse_client=clickhouse_client,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        exclude_events=exclude_events,
    )


async def test_http_export_workflow_handles_insert_activity_errors(ateam, http_batch_export, interval):
    """Test that HTTP Export Workflow can gracefully handle errors when POSTing to HTTP Endpoint."""
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid4())
    inputs = HttpBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(http_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **http_batch_export.destination.config,
    )

    @activity.defn(name="insert_into_http_activity")
    async def insert_into_http_activity_mocked(_: HttpInsertInputs) -> str:
        raise ValueError("A useful error message")

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[HttpBatchExportWorkflow],
            activities=[
                mocked_start_batch_export_run,
                insert_into_http_activity_mocked,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await activity_environment.client.execute_workflow(
                    HttpBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    runs = await afetch_batch_export_runs(batch_export_id=http_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "FailedRetryable"
    assert run.latest_error == "ValueError: A useful error message"
    assert run.records_completed is None


async def test_http_export_workflow_handles_insert_activity_non_retryable_errors(ateam, http_batch_export, interval):
    """Test that HTTP Export Workflow can gracefully handle non-retryable errors when POSTing to HTTP Endpoint."""
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid4())
    inputs = HttpBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(http_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **http_batch_export.destination.config,
    )

    class NonRetryableResponseError(Exception):
        pass

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[HttpBatchExportWorkflow],
            activities=[
                mocked_start_batch_export_run,
                insert_into_http_activity,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with unittest.mock.patch(
                "products.batch_exports.backend.temporal.destinations.http_batch_export.aiohttp.ClientSession",
                side_effect=NonRetryableResponseError("A useful error message"),
            ):
                await activity_environment.client.execute_workflow(
                    HttpBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    runs = await afetch_batch_export_runs(batch_export_id=http_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Failed"
    assert run.latest_error == "NonRetryableResponseError: A useful error message"
    assert run.records_completed is None


async def test_http_export_workflow_handles_cancellation(ateam, http_batch_export, interval):
    """Test that HTTP Export Workflow can gracefully handle cancellations when POSTing to HTTP Endpoint."""
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid4())
    inputs = HttpBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(http_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **http_batch_export.destination.config,
    )

    @activity.defn(name="insert_into_http_activity")
    async def never_finish_activity(_: HttpInsertInputs) -> str:
        while True:
            activity.heartbeat()
            await asyncio.sleep(1)

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[HttpBatchExportWorkflow],
            activities=[
                mocked_start_batch_export_run,
                never_finish_activity,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await activity_environment.client.start_workflow(
                HttpBatchExportWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=settings.TEMPORAL_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            await asyncio.sleep(5)
            await handle.cancel()

            with pytest.raises(WorkflowFailureError):
                await handle.result()

    runs = await afetch_batch_export_runs(batch_export_id=http_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Cancelled"
    assert run.latest_error == "Cancelled"


async def test_insert_into_http_activity_heartbeats(
    clickhouse_client,
    ateam,
    http_batch_export,
    activity_environment,
    http_config,
):
    """Test that the insert_into_http_activity activity sends heartbeats.

    We use a function that runs on_heartbeat to check and track the heartbeat contents.
    """
    data_interval_end = dt.datetime.now(tz=dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    data_interval_start = data_interval_end - http_batch_export.interval_time_delta

    num_expected_parts = 3

    for i in range(1, num_expected_parts + 1):
        part_inserted_at = data_interval_end - http_batch_export.interval_time_delta / i

        await generate_test_events_in_clickhouse(
            client=clickhouse_client,
            team_id=ateam.pk,
            start_time=data_interval_start,
            end_time=data_interval_end,
            count=1,
            count_outside_range=0,
            count_other_team=0,
            duplicate=False,
            # We need to roll over 5MB to trigger a batch flush (and a heartbeat).
            properties={"$chonky": ("a" * 5 * 1024**2)},
            inserted_at=part_inserted_at,
        )

    heartbeat_count = 0

    def assert_heartbeat_details(*raw_details):
        """A function to track and assert we are heartbeating."""
        nonlocal heartbeat_count
        heartbeat_count += 1

        details = HeartbeatDetails.from_activity_details(raw_details)

        last_uploaded_dt = dt.datetime.fromisoformat(details.last_uploaded_timestamp)
        assert last_uploaded_dt == data_interval_end - http_batch_export.interval_time_delta / heartbeat_count

    activity_environment.on_heartbeat = assert_heartbeat_details

    insert_inputs = HttpInsertInputs(
        team_id=ateam.pk,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        **http_config,
    )

    mock_server = MockServer()
    with (
        aioresponses(passthrough=[settings.CLICKHOUSE_HTTP_URL]) as m,
        override_settings(BATCH_EXPORT_HTTP_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2),
    ):
        m.post(TEST_URL, status=200, callback=mock_server.post, repeat=True)
        await activity_environment.run(insert_into_http_activity, insert_inputs)

    # This checks that the assert_heartbeat_details function was actually called.
    assert heartbeat_count == num_expected_parts

    await assert_clickhouse_records_in_mock_server(
        mock_server=mock_server,
        clickhouse_client=clickhouse_client,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
    )
