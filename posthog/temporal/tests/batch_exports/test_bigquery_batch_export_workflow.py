import asyncio
import datetime as dt
import json
import os
from random import randint
from uuid import uuid4

import pytest
import pytest_asyncio
from asgiref.sync import sync_to_async
from django.conf import settings
from freezegun.api import freeze_time
from google.cloud import bigquery
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.api.test.test_organization import acreate_organization
from posthog.api.test.test_team import acreate_team
from posthog.temporal.client import connect
from posthog.temporal.tests.batch_exports.base import (
    EventValues,
    amaterialize,
    insert_events,
)
from posthog.temporal.tests.batch_exports.fixtures import (
    acreate_batch_export,
    adelete_batch_export,
    afetch_batch_export_runs,
)
from posthog.temporal.workflows.base import create_export_run, update_export_run_status
from posthog.temporal.workflows.bigquery_batch_export import (
    BigQueryBatchExportInputs,
    BigQueryBatchExportWorkflow,
    BigQueryInsertInputs,
    insert_into_bigquery_activity,
)
from posthog.temporal.workflows.clickhouse import ClickHouseClient

TEST_TIME = dt.datetime.utcnow()


def assert_events_in_bigquery(client, table_id, dataset_id, events, bq_ingested_timestamp):
    """Assert provided events written to a given BigQuery table."""
    query_job = client.query(f"SELECT * FROM {dataset_id}.{table_id} ORDER BY timestamp")
    result = query_job.result()

    inserted_events = []
    json_columns = ("properties", "elements", "set", "set_once")

    for row in result:
        inserted_event = {k: json.loads(v) if k in json_columns and v is not None else v for k, v in row.items()}
        inserted_events.append(inserted_event)

    expected_events = []
    for event in events:
        properties = event.get("properties", None)
        elements_chain = event.get("elements_chain", None)
        expected_event = {
            "bq_ingested_timestamp": bq_ingested_timestamp,
            "distinct_id": event.get("distinct_id"),
            "elements": json.dumps(elements_chain),
            "event": event.get("event"),
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

    expected_events.sort(key=lambda x: x["timestamp"])

    # First check one event, the first one, so that we can get a nice diff if
    # the included data is different.
    assert inserted_events[0] == expected_events[0]
    assert len(inserted_events) == len(expected_events)
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
        # Not part of the credentials.
        # Hardcoded to test dataset.
        "dataset_id": "BatchExports",
    }


@pytest.fixture
def bigquery_client() -> bigquery.Client:
    client = bigquery.Client()

    try:
        yield client
    finally:
        client.close()


@pytest.mark.skipif(
    "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ,
    reason="Google credentials not set in environment",
)
@pytest.mark.django_db
@pytest.mark.asyncio
async def test_insert_into_bigquery_activity_inserts_data_into_bigquery_table(
    activity_environment, bigquery_client, bigquery_config
):
    """Test that the insert_into_bigquery_activity function inserts data into a Bigquery table."""

    data_interval_start = "2023-04-20 14:00:00"
    data_interval_end = "2023-04-25 15:00:00"

    # Generate a random team id integer. There's still a chance of a collision,
    # but it's very small.
    team_id = randint(1, 1000000)

    # Add a materialized column such that we can verify that it is NOT included
    # in the export.
    await amaterialize("events", "$browser")

    events: list[EventValues] = [
        {
            "uuid": str(uuid4()),
            "event": "test",
            "_timestamp": "2023-04-20 14:30:00",
            "timestamp": f"2023-04-20 14:30:00.{i:06d}",
            "inserted_at": f"2023-04-20 14:30:00.{i:06d}",
            "created_at": "2023-04-20 14:30:00.000000",
            "distinct_id": str(uuid4()),
            "person_id": str(uuid4()),
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team_id,
            "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "elements_chain": "",
        }
        # NOTE: we have to do a lot here, otherwise we do not trigger a
        # multipart upload, and the minimum part chunk size is 5MB.
        for i in range(10000)
    ]

    events += [
        # Insert an events with an empty string in `properties` and
        # `person_properties` to ensure that we handle empty strings correctly.
        EventValues(
            {
                "uuid": str(uuid4()),
                "event": "test",
                "_timestamp": "2023-04-20 14:29:00",
                "timestamp": "2023-04-20 14:29:00.000000",
                "inserted_at": "2023-04-20 14:30:00.000000",
                "created_at": "2023-04-20 14:29:00.000000",
                "distinct_id": str(uuid4()),
                "person_id": str(uuid4()),
                "person_properties": None,
                "team_id": team_id,
                "properties": None,
                "elements_chain": "",
            }
        )
    ]

    ch_client = ClickHouseClient(
        url=settings.CLICKHOUSE_HTTP_URL,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
    )

    # Insert some data into the `sharded_events` table.
    await insert_events(
        client=ch_client,
        events=events,
    )

    # Insert some events before the hour and after the hour, as well as some
    # events from another team to ensure that we only export the events from
    # the team that the batch export is for.
    other_team_id = team_id + 1
    await insert_events(
        client=ch_client,
        events=[
            {
                "uuid": str(uuid4()),
                "event": "test",
                "timestamp": "2023-04-20 13:30:00",
                "_timestamp": "2023-04-20 13:30:00",
                "inserted_at": "2023-04-20 13:30:00.000000",
                "created_at": "2023-04-20 13:30:00.000000",
                "person_id": str(uuid4()),
                "distinct_id": str(uuid4()),
                "team_id": team_id,
                "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "elements_chain": 'strong.pricingpage:attr__class="pricingpage"nth-child="1"nth-of-type="1"text="A question?";',
            },
            {
                "uuid": str(uuid4()),
                "event": "test",
                "timestamp": "2023-04-20 15:30:00",
                "_timestamp": "2023-04-20 13:30:00",
                "inserted_at": "2023-04-20 13:30:00.000000",
                "created_at": "2023-04-20 13:30:00.000000",
                "person_id": str(uuid4()),
                "distinct_id": str(uuid4()),
                "team_id": team_id,
                "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "elements_chain": 'strong.pricingpage:attr__class="pricingpage"nth-child="1"nth-of-type="1"text="A question?";',
            },
            {
                "uuid": str(uuid4()),
                "event": "test",
                "timestamp": "2023-04-20 14:30:00",
                "_timestamp": "2023-04-20 14:30:00",
                "inserted_at": "2023-04-20 14:30:00.000000",
                "created_at": "2023-04-20 14:30:00.000000",
                "person_id": str(uuid4()),
                "distinct_id": str(uuid4()),
                "team_id": other_team_id,
                "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "elements_chain": 'strong.pricingpage:attr__class="pricingpage"nth-child="1"nth-of-type="1"text="A question?";',
            },
        ],
    )

    insert_inputs = BigQueryInsertInputs(
        team_id=team_id,
        table_id=f"test_insert_activity_table_{team_id}",
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        **bigquery_config,
    )

    with freeze_time(TEST_TIME) as frozen_time:
        await activity_environment.run(insert_into_bigquery_activity, insert_inputs)

        ingested_timestamp = frozen_time().replace(tzinfo=dt.timezone.utc)

        assert_events_in_bigquery(
            client=bigquery_client,
            table_id=f"test_insert_activity_table_{team_id}",
            dataset_id=bigquery_config["dataset_id"],
            events=events,
            bq_ingested_timestamp=ingested_timestamp,
        )


@pytest.mark.skipif(
    "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ,
    reason="Google credentials not set in environment",
)
@pytest.mark.django_db
@pytest.mark.asyncio
@pytest.mark.parametrize("interval", ["hour", "day"])
async def test_bigquery_export_workflow(
    bigquery_config,
    bigquery_client,
    interval,
):
    """Test BigQuery Export Workflow end-to-end by using a local PG database."""
    organization = await acreate_organization("test")
    team = await acreate_team(organization=organization)

    test_table_id = f"test_workflow_table_{team.pk}_{interval}"
    destination_data = {"type": "BigQuery", "config": {**bigquery_config, "table_id": test_table_id}}
    batch_export_data = {
        "name": "my-production-bigquery-export",
        "destination": destination_data,
        "interval": interval,
    }

    batch_export = await acreate_batch_export(
        team_id=team.pk,
        name=batch_export_data["name"],
        destination_data=batch_export_data["destination"],
        interval=batch_export_data["interval"],
    )

    events: list[EventValues] = [
        {
            "uuid": str(uuid4()),
            "event": "test",
            "timestamp": "2023-04-25 13:30:00.000000",
            "created_at": "2023-04-25 13:30:00.000000",
            "inserted_at": "2023-04-25 13:30:00.000000",
            "_timestamp": "2023-04-25 13:30:00",
            "person_id": str(uuid4()),
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team.pk,
            "properties": {
                "$browser": "Chrome",
                "$os": "Mac OS X",
                "$ip": "172.16.0.1",
                "$current_url": "https://app.posthog.com",
            },
            "distinct_id": str(uuid4()),
            "elements_chain": 'strong.pricingpage:attr__class="pricingpage"nth-child="1"nth-of-type="1"text="A question?";',
        },
        {
            "uuid": str(uuid4()),
            "event": "test",
            "timestamp": "2023-04-25 14:29:00.000000",
            "created_at": "2023-04-25 14:29:00.000000",
            "inserted_at": "2023-04-25 14:29:00.000000",
            "_timestamp": "2023-04-25 14:29:00",
            "person_id": str(uuid4()),
            "properties": {
                "$browser": "Chrome",
                "$os": "Mac OS X",
                "$current_url": "https://app.posthog.com",
                "$ip": "172.16.0.1",
            },
            "team_id": team.pk,
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "distinct_id": str(uuid4()),
            "elements_chain": 'strong.pricingpage:attr__class="pricingpage"nth-child="1"nth-of-type="1"text="A question?";',
        },
    ]

    if interval == "day":
        # Add an event outside the hour range but within the day range to ensure it's exported too.
        events_outside_hour: list[EventValues] = [
            {
                "uuid": str(uuid4()),
                "event": "test",
                "timestamp": "2023-04-25 00:30:00.000000",
                "created_at": "2023-04-25 00:30:00.000000",
                "inserted_at": "2023-04-25 00:30:00.000000",
                "_timestamp": "2023-04-25 00:30:00",
                "person_id": str(uuid4()),
                "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "team_id": team.pk,
                "properties": {
                    "$browser": "Chrome",
                    "$os": "Mac OS X",
                    "$current_url": "https://app.posthog.com",
                    "$ip": "172.16.0.1",
                },
                "distinct_id": str(uuid4()),
                "elements_chain": 'strong.pricingpage:attr__class="pricingpage"nth-child="1"nth-of-type="1"text="A question?";',
            }
        ]
        events += events_outside_hour

    ch_client = ClickHouseClient(
        url=settings.CLICKHOUSE_HTTP_URL,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
    )

    await insert_events(
        client=ch_client,
        events=events,
    )

    workflow_id = str(uuid4())
    inputs = BigQueryBatchExportInputs(
        team_id=team.pk,
        batch_export_id=str(batch_export.id),
        data_interval_end="2023-04-25 14:30:00.000000",
        interval=interval,
        **batch_export.destination.config,
    )

    with freeze_time(TEST_TIME) as frozen_time:
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=settings.TEMPORAL_TASK_QUEUE,
                workflows=[BigQueryBatchExportWorkflow],
                activities=[create_export_run, insert_into_bigquery_activity, update_export_run_status],
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

                runs = await afetch_batch_export_runs(batch_export_id=batch_export.id)
                assert len(runs) == 1

                run = runs[0]
                assert run.status == "Completed"

                ingested_timestamp = frozen_time().replace(tzinfo=dt.timezone.utc)
                assert_events_in_bigquery(
                    client=bigquery_client,
                    table_id=test_table_id,
                    dataset_id=bigquery_config["dataset_id"],
                    events=events,
                    bq_ingested_timestamp=ingested_timestamp,
                )


@pytest_asyncio.fixture
async def organization():
    organization = await acreate_organization("test")
    yield organization
    await sync_to_async(organization.delete)()  # type: ignore


@pytest_asyncio.fixture
async def team(organization):
    team = await acreate_team(organization=organization)
    yield team
    await sync_to_async(team.delete)()  # type: ignore


@pytest_asyncio.fixture
async def batch_export(team):
    destination_data = {
        "type": "BigQuery",
        "config": {
            "table_id": f"test_workflow_table_{team.pk}",
            "project_id": "project_id",
            "private_key": "private_key",
            "private_key_id": "private_key_id",
            "token_uri": "token_uri",
            "client_email": "client_email",
            "dataset_id": "BatchExports",
        },
    }
    batch_export_data = {
        "name": "my-production-bigquery-export",
        "destination": destination_data,
        "interval": "hour",
    }

    batch_export = await acreate_batch_export(
        team_id=team.pk,
        name=batch_export_data["name"],
        destination_data=batch_export_data["destination"],
        interval=batch_export_data["interval"],
    )

    yield batch_export

    client = await connect(
        settings.TEMPORAL_HOST,
        settings.TEMPORAL_PORT,
        settings.TEMPORAL_NAMESPACE,
        settings.TEMPORAL_CLIENT_ROOT_CA,
        settings.TEMPORAL_CLIENT_CERT,
        settings.TEMPORAL_CLIENT_KEY,
    )
    await adelete_batch_export(batch_export, client)


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_bigquery_export_workflow_handles_insert_activity_errors(team, batch_export):
    """Test that BigQuery Export Workflow can gracefully handle errors when inserting BigQuery data."""
    workflow_id = str(uuid4())
    inputs = BigQueryBatchExportInputs(
        team_id=team.pk,
        batch_export_id=str(batch_export.id),
        data_interval_end="2023-04-25 14:30:00.000000",
        **batch_export.destination.config,
    )

    @activity.defn(name="insert_into_bigquery_activity")
    async def insert_into_bigquery_activity_mocked(_: BigQueryInsertInputs) -> str:
        raise ValueError("A useful error message")

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[BigQueryBatchExportWorkflow],
            activities=[create_export_run, insert_into_bigquery_activity_mocked, update_export_run_status],
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

        runs = await afetch_batch_export_runs(batch_export_id=batch_export.id)
        assert len(runs) == 1

        run = runs[0]
        assert run.status == "Failed"
        assert run.latest_error == "ValueError: A useful error message"


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_bigquery_export_workflow_handles_cancellation(team, batch_export):
    """Test that BigQuery Export Workflow can gracefully handle cancellations when inserting BigQuery data."""
    workflow_id = str(uuid4())
    inputs = BigQueryBatchExportInputs(
        team_id=team.pk,
        batch_export_id=str(batch_export.id),
        data_interval_end="2023-04-25 14:30:00.000000",
        **batch_export.destination.config,
    )

    @activity.defn(name="insert_into_s3_activity")
    async def never_finish_activity(_: BigQueryInsertInputs) -> str:
        while True:
            activity.heartbeat()
            await asyncio.sleep(1)

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[BigQueryBatchExportWorkflow],
            activities=[create_export_run, never_finish_activity, update_export_run_status],
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

        runs = await afetch_batch_export_runs(batch_export_id=batch_export.id)
        assert len(runs) == 1

        run = runs[0]
        assert run.status == "Cancelled"
        assert run.latest_error == "Cancelled"
