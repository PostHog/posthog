import asyncio
import datetime as dt
import json
import os
import typing
from random import randint
from uuid import uuid4

import pytest
import pytest_asyncio
from django.conf import settings
from freezegun.api import freeze_time
from google.cloud import bigquery
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.batch_exports.batch_exports import (
    create_export_run,
    update_export_run_status,
)
from posthog.temporal.batch_exports.bigquery_batch_export import (
    BigQueryBatchExportInputs,
    BigQueryBatchExportWorkflow,
    BigQueryInsertInputs,
    insert_into_bigquery_activity,
)
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse
from posthog.temporal.tests.utils.models import (
    acreate_batch_export,
    adelete_batch_export,
    afetch_batch_export_runs,
)

SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS = pytest.mark.skipif(
    "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ,
    reason="Google credentials not set in environment",
)

pytestmark = [SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS, pytest.mark.asyncio, pytest.mark.django_db]


TEST_TIME = dt.datetime.utcnow()


def assert_events_in_bigquery(
    client, table_id, dataset_id, events, bq_ingested_timestamp, exclude_events: list[str] | None = None
):
    """Assert provided events written to a given BigQuery table."""
    query_job = client.query(f"SELECT * FROM {dataset_id}.{table_id} ORDER BY event, timestamp")
    result = query_job.result()

    inserted_events = []
    json_columns = ("properties", "elements", "set", "set_once")

    for row in result:
        inserted_event = {k: json.loads(v) if k in json_columns and v is not None else v for k, v in row.items()}
        inserted_events.append(inserted_event)

    # Reconstruct bq_ingested_timestamp in case we are faking dates.
    bq_ingested_timestamp = dt.datetime(
        bq_ingested_timestamp.year,
        bq_ingested_timestamp.month,
        bq_ingested_timestamp.day,
        bq_ingested_timestamp.hour,
        bq_ingested_timestamp.minute,
        bq_ingested_timestamp.second,
        bq_ingested_timestamp.microsecond,
        bq_ingested_timestamp.tzinfo,
    )

    expected_events = []
    for event in events:
        event_name = event.get("event")

        if exclude_events is not None and event_name in exclude_events:
            continue

        properties = event.get("properties", None)
        elements_chain = event.get("elements_chain", None)
        expected_event = {
            "bq_ingested_timestamp": bq_ingested_timestamp,
            "distinct_id": event.get("distinct_id"),
            "elements": json.dumps(elements_chain),
            "event": event_name,
            "ip": properties.get("$ip", None) if properties else None,
            "properties": event.get("properties"),
            "set": properties.get("$set", None) if properties else None,
            "set_once": properties.get("$set_once", None) if properties else None,
            "site_url": "",
            # For compatibility with CH which doesn't parse timezone component, so we add it here assuming UTC.
            "timestamp": dt.datetime.fromisoformat(event.get("timestamp") + "+00:00"),
            "team_id": event.get("team_id"),
            "uuid": event.get("uuid"),
        }
        expected_events.append(expected_event)

    expected_events.sort(key=lambda x: (x["event"], x["timestamp"]))

    # First check one event, the first one, so that we can get a nice diff if
    # the included data is different.
    assert inserted_events[0] == expected_events[0]
    assert inserted_events == expected_events


@pytest.fixture
def bigquery_config() -> dict[str, str]:
    """Return a BigQuery configuration dictionary to use in tests."""
    credentials_file_path = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    with open(credentials_file_path) as f:
        credentials = json.load(f)

    return {
        "project_id": credentials["project_id"],
        "private_key": credentials["private_key"],
        "private_key_id": credentials["private_key_id"],
        "token_uri": credentials["token_uri"],
        "client_email": credentials["client_email"],
    }


@pytest.fixture
def bigquery_client() -> typing.Generator[bigquery.Client, None, None]:
    """Manage a bigquery.Client for testing."""
    client = bigquery.Client()

    yield client

    client.close()


@pytest.fixture
def bigquery_dataset(bigquery_config, bigquery_client) -> typing.Generator[bigquery.Dataset, None, None]:
    """Manage a bigquery dataset for testing.

    We clean up the dataset after every test. Could be quite time expensive, but guarantees a clean slate.
    """
    dataset_id = f"{bigquery_config['project_id']}.BatchExportsTest_{str(uuid4()).replace('-', '')}"

    dataset = bigquery.Dataset(dataset_id)
    dataset = bigquery_client.create_dataset(dataset)

    yield dataset

    bigquery_client.delete_dataset(dataset_id, delete_contents=True, not_found_ok=True)


@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
async def test_insert_into_bigquery_activity_inserts_data_into_bigquery_table(
    clickhouse_client, activity_environment, bigquery_client, bigquery_config, exclude_events, bigquery_dataset
):
    """Test that the insert_into_bigquery_activity function inserts data into a BigQuery table.

    We use the generate_test_events_in_clickhouse function to generate several sets
    of events. Some of these sets are expected to be exported, and others not. Expected
    events are those that:
    * Are created for the team_id of the batch export.
    * Are created in the date range of the batch export.
    * Are not duplicates of other events that are in the same batch.
    * Do not have an event name contained in the batch export's exclude_events.

    Once we have these events, we pass them to the assert_events_in_bigquery function to check
    that they appear in the expected BigQuery table.
    """
    data_interval_start = dt.datetime(2023, 4, 20, 14, 0, 0, tzinfo=dt.timezone.utc)
    data_interval_end = dt.datetime(2023, 4, 25, 15, 0, 0, tzinfo=dt.timezone.utc)

    # Generate a random team id integer. There's still a chance of a collision,
    # but it's very small.
    team_id = randint(1, 1000000)

    (events, _, _) = await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=team_id,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=1000,
        count_outside_range=10,
        count_other_team=10,
        duplicate=True,
        properties={"$browser": "Chrome", "$os": "Mac OS X"},
        person_properties={"utm_medium": "referral", "$initial_os": "Linux"},
    )

    (events_with_no_properties, _, _) = await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=team_id,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=5,
        count_outside_range=0,
        count_other_team=0,
        properties=None,
        person_properties=None,
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
            )

    insert_inputs = BigQueryInsertInputs(
        team_id=team_id,
        table_id=f"test_insert_activity_table_{team_id}",
        dataset_id=bigquery_dataset.dataset_id,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        **bigquery_config,
    )

    with freeze_time(TEST_TIME) as frozen_time:
        await activity_environment.run(insert_into_bigquery_activity, insert_inputs)

        ingested_timestamp = frozen_time().replace(tzinfo=dt.timezone.utc)

        assert_events_in_bigquery(
            client=bigquery_client,
            table_id=f"test_insert_activity_table_{team_id}",
            dataset_id=bigquery_dataset.dataset_id,
            events=events + events_with_no_properties,
            bq_ingested_timestamp=ingested_timestamp,
            exclude_events=exclude_events,
        )


@pytest.fixture
def table_id(ateam, interval):
    return f"test_workflow_table_{ateam.pk}_{interval}"


@pytest_asyncio.fixture
async def bigquery_batch_export(
    ateam, table_id, bigquery_config, interval, exclude_events, temporal_client, bigquery_dataset
):
    destination_data = {
        "type": "BigQuery",
        "config": {
            **bigquery_config,
            "table_id": table_id,
            "dataset_id": bigquery_dataset.dataset_id,
            "exclude_events": exclude_events,
        },
    }

    batch_export_data = {
        "name": "my-production-bigquery-destination",
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


@pytest.mark.parametrize("interval", ["hour", "day"])
@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
async def test_bigquery_export_workflow(
    clickhouse_client,
    bigquery_client,
    bigquery_batch_export,
    interval,
    exclude_events,
    ateam,
    table_id,
):
    """Test BigQuery Export Workflow end-to-end.

    The workflow should update the batch export run status to completed and produce the expected
    records to the configured BigQuery table.
    """
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")
    data_interval_start = data_interval_end - bigquery_batch_export.interval_time_delta

    (events, _, _) = await generate_test_events_in_clickhouse(
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
    inputs = BigQueryBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(bigquery_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **bigquery_batch_export.destination.config,
    )

    with freeze_time(TEST_TIME) as frozen_time:
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=settings.TEMPORAL_TASK_QUEUE,
                workflows=[BigQueryBatchExportWorkflow],
                activities=[
                    create_export_run,
                    insert_into_bigquery_activity,
                    update_export_run_status,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                await activity_environment.client.execute_workflow(
                    BigQueryBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=dt.timedelta(seconds=10),
                )

        runs = await afetch_batch_export_runs(batch_export_id=bigquery_batch_export.id)
        assert len(runs) == 1

        run = runs[0]
        assert run.status == "Completed"

        ingested_timestamp = frozen_time().replace(tzinfo=dt.timezone.utc)
        assert_events_in_bigquery(
            client=bigquery_client,
            table_id=table_id,
            dataset_id=bigquery_batch_export.destination.config["dataset_id"],
            events=events,
            bq_ingested_timestamp=ingested_timestamp,
            exclude_events=exclude_events,
        )


async def test_bigquery_export_workflow_handles_insert_activity_errors(ateam, bigquery_batch_export, interval):
    """Test that BigQuery Export Workflow can gracefully handle errors when inserting BigQuery data."""
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid4())
    inputs = BigQueryBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(bigquery_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **bigquery_batch_export.destination.config,
    )

    @activity.defn(name="insert_into_bigquery_activity")
    async def insert_into_bigquery_activity_mocked(_: BigQueryInsertInputs) -> str:
        raise ValueError("A useful error message")

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[BigQueryBatchExportWorkflow],
            activities=[
                create_export_run,
                insert_into_bigquery_activity_mocked,
                update_export_run_status,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await activity_environment.client.execute_workflow(
                    BigQueryBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    runs = await afetch_batch_export_runs(batch_export_id=bigquery_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Failed"
    assert run.latest_error == "ValueError: A useful error message"


async def test_bigquery_export_workflow_handles_cancellation(ateam, bigquery_batch_export, interval):
    """Test that BigQuery Export Workflow can gracefully handle cancellations when inserting BigQuery data."""
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid4())
    inputs = BigQueryBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(bigquery_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **bigquery_batch_export.destination.config,
    )

    @activity.defn(name="insert_into_bigquery_activity")
    async def never_finish_activity(_: BigQueryInsertInputs) -> str:
        while True:
            activity.heartbeat()
            await asyncio.sleep(1)

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[BigQueryBatchExportWorkflow],
            activities=[
                create_export_run,
                never_finish_activity,
                update_export_run_status,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await activity_environment.client.start_workflow(
                BigQueryBatchExportWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=settings.TEMPORAL_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )

            await asyncio.sleep(5)
            await handle.cancel()

            with pytest.raises(WorkflowFailureError):
                await handle.result()

    runs = await afetch_batch_export_runs(batch_export_id=bigquery_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Cancelled"
    assert run.latest_error == "Cancelled"
