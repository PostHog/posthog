import asyncio
import datetime as dt
import gzip
import json
import os
import random
import re
from collections import deque
from uuid import uuid4

import pytest
import pytest_asyncio
import responses
import snowflake.connector
from django.conf import settings
from django.test import override_settings
from requests.models import PreparedRequest
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.tests.utils.datetimes import to_isoformat
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse
from posthog.temporal.tests.utils.models import acreate_batch_export, adelete_batch_export, afetch_batch_export_runs
from posthog.temporal.workflows.batch_exports import (
    create_export_run,
    update_export_run_status,
)
from posthog.temporal.workflows.snowflake_batch_export import (
    SnowflakeBatchExportInputs,
    SnowflakeBatchExportWorkflow,
    SnowflakeInsertInputs,
    insert_into_snowflake_activity,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


def contains_queries_in_order(queries: list[str], *queries_to_find: str):
    """Check if a list of queries contains a list of queries in order."""
    # We use a deque to pop the queries we find off the list of queries to
    # find, so that we can check that they are in order.
    # Note that we use regexes to match the queries, so we can more specifically
    # target the queries we want to find.
    queries_to_find_deque = deque(queries_to_find)
    for query in queries:
        if not queries_to_find_deque:
            # We've found all the queries we need to find.
            return True
        if re.match(queries_to_find_deque[0], query):
            # We found the query we were looking for, so pop it off the deque.
            queries_to_find_deque.popleft()
    return not queries_to_find_deque


def add_mock_snowflake_api(rsps: responses.RequestsMock, fail: bool | str = False):
    # Create a crube mock of the Snowflake API that just stores the queries
    # in a list for us to inspect.
    #
    # We also mock the login request, as well as the PUT file transfer
    # request. For the latter we also store the data that was contained in
    # the file.
    queries = []
    staged_files = []

    def query_request_handler(request: PreparedRequest):
        assert isinstance(request.body, bytes)
        sql_text = json.loads(gzip.decompress(request.body))["sqlText"]
        queries.append(sql_text)

        rowset = [("test", "LOADED", 456, 192, "NONE", "GZIP", "UPLOADED", "")]

        # If the query is something that looks like `PUT file:///tmp/tmp50nod7v9
        # @%"events"` we extract the /tmp/tmp50nod7v9 and store the file
        # contents as a string in `staged_files`.
        if match := re.match(r"^PUT file://(?P<file_path>.*) @%(?P<table_name>.*)$", sql_text):
            file_path = match.group("file_path")
            with open(file_path, "r") as f:
                staged_files.append(f.read())

            if fail == "put":
                rowset = [
                    (
                        "test",
                        "test.gz",
                        456,
                        0,
                        "NONE",
                        "GZIP",
                        "FAILED",
                        "Some error on put",
                    )
                ]

        else:
            if fail == "copy":
                rowset = [("test", "LOAD FAILED", 100, 99, 1, 1, "Some error on copy", 3)]

        return (
            200,
            {},
            json.dumps(
                {
                    "code": None,
                    "message": None,
                    "success": True,
                    "data": {
                        "parameters": [],
                        "rowtype": [
                            {
                                "name": "source",
                                "type": "TEXT",
                                "length": 0,
                                "precision": None,
                                "scale": None,
                                "nullable": True,
                            },
                            {
                                "name": "target",
                                "type": "TEXT",
                                "length": 0,
                                "precision": None,
                                "scale": None,
                                "nullable": True,
                            },
                            {
                                "name": "source_size",
                                "type": "fixed",
                                "length": 0,
                                "precision": None,
                                "scale": None,
                                "nullable": True,
                            },
                            {
                                "name": "target_size",
                                "type": "fixed",
                                "length": 0,
                                "precision": None,
                                "scale": None,
                                "nullable": True,
                            },
                            {
                                "name": "source_compression",
                                "type": "TEXT",
                                "length": 0,
                                "precision": None,
                                "scale": None,
                                "nullable": True,
                            },
                            {
                                "name": "target_compression",
                                "type": "TEXT",
                                "length": 0,
                                "precision": None,
                                "scale": None,
                                "nullable": True,
                            },
                            {
                                "name": "status",
                                "type": "TEXT",
                                "length": 0,
                                "precision": None,
                                "scale": None,
                                "nullable": True,
                            },
                            {
                                "name": "message",
                                "type": "TEXT",
                                "length": 0,
                                "precision": None,
                                "scale": None,
                                "nullable": True,
                            },
                        ],
                        "rowset": rowset,
                        "total": 1,
                        "returned": 1,
                        "queryId": "query-id",
                        "queryResultFormat": "json",
                    },
                }
            ),
        )

    rsps.add(
        responses.POST,
        "https://account.snowflakecomputing.com:443/session/v1/login-request",
        json={
            "success": True,
            "data": {
                "token": "test-token",
                "masterToken": "test-token",
                "code": None,
                "message": None,
            },
        },
    )
    rsps.add_callback(
        responses.POST,
        "https://account.snowflakecomputing.com:443/queries/v1/query-request",
        callback=query_request_handler,
    )

    return queries, staged_files


@pytest.fixture
def database():
    """Generate a unique database name for tests."""
    return f"test_batch_exports_{uuid4()}"


@pytest.fixture
def schema():
    """Generate a unique schema name for tests."""
    return f"test_batch_exports_{uuid4()}"


@pytest.fixture
def table_name(ateam, interval):
    return f"test_workflow_table_{ateam.pk}_{interval}"


@pytest.fixture
def snowflake_config(database, schema) -> dict[str, str]:
    """Return a Snowflake configuration dictionary to use in tests.

    We set default configuration values to support tests against the Snowflake API
    and tests that mock it.
    """
    password = os.getenv("SNOWFLAKE_PASSWORD", "password")
    warehouse = os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH")
    account = os.getenv("SNOWFLAKE_ACCOUNT", "account")
    username = os.getenv("SNOWFLAKE_USERNAME", "hazzadous")

    return {
        "password": password,
        "user": username,
        "warehouse": warehouse,
        "account": account,
        "database": database,
        "schema": schema,
    }


@pytest_asyncio.fixture
async def snowflake_batch_export(ateam, table_name, snowflake_config, interval, exclude_events, temporal_client):
    """Manage BatchExport model (and associated Temporal Schedule) for tests"""
    destination_data = {
        "type": "Snowflake",
        "config": {**snowflake_config, "table_name": table_name, "exclude_events": exclude_events},
    }
    batch_export_data = {
        "name": "my-production-snowflake-export",
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
async def test_snowflake_export_workflow_exports_events(ateam, clickhouse_client, snowflake_batch_export, interval):
    """Test that the whole workflow not just the activity works.

    It should update the batch export run status to completed, as well as updating the record
    count.
    """
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")
    data_interval_start = data_interval_end - snowflake_batch_export.interval_time_delta

    (events, _, _) = await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=ateam.pk,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=10,
        count_outside_range=10,
        count_other_team=10,
        duplicate=True,
        properties={"$browser": "Chrome", "$os": "Mac OS X"},
        person_properties={"utm_medium": "referral", "$initial_os": "Linux"},
    )

    workflow_id = str(uuid4())
    inputs = SnowflakeBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(snowflake_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **snowflake_batch_export.destination.config,
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[SnowflakeBatchExportWorkflow],
            activities=[
                create_export_run,
                insert_into_snowflake_activity,
                update_export_run_status,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with responses.RequestsMock(
                target="snowflake.connector.vendored.requests.adapters.HTTPAdapter.send"
            ) as rsps, override_settings(BATCH_EXPORT_SNOWFLAKE_UPLOAD_CHUNK_SIZE_BYTES=1**2):
                queries, staged_files = add_mock_snowflake_api(rsps)
                await activity_environment.client.execute_workflow(
                    SnowflakeBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    execution_timeout=dt.timedelta(seconds=10),
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

                assert contains_queries_in_order(
                    queries,
                    'USE DATABASE "PostHog"',
                    'USE SCHEMA "test"',
                    'CREATE TABLE IF NOT EXISTS "PostHog"."test"."events"',
                    # NOTE: we check that we at least have two PUT queries to
                    # ensure we hit the multi file upload code path
                    'PUT file://.* @%"events"',
                    'PUT file://.* @%"events"',
                    'COPY INTO "events"',
                )

                staged_data = "\n".join(staged_files)

                # Check that the data is correct.
                json_data = [json.loads(line) for line in staged_data.split("\n") if line]
                # Pull out the fields we inserted only
                json_data = [
                    {
                        "uuid": event["uuid"],
                        "event": event["event"],
                        "timestamp": event["timestamp"],
                        "properties": event["properties"],
                        "person_id": event["person_id"],
                    }
                    for event in json_data
                ]
                json_data.sort(key=lambda x: x["timestamp"])

                # Drop _timestamp and team_id from events
                expected_events = []
                for event in events:
                    expected_event = {
                        key: value
                        for key, value in event.items()
                        if key in ("uuid", "event", "timestamp", "properties", "person_id")
                    }
                    expected_event["timestamp"] = to_isoformat(event["timestamp"])
                    expected_events.append(expected_event)
                expected_events.sort(key=lambda x: x["timestamp"])

                assert json_data[0] == expected_events[0]
                assert json_data == expected_events

    runs = await afetch_batch_export_runs(batch_export_id=snowflake_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"


@pytest.mark.parametrize("interval", ["hour", "day"], indirect=True)
async def test_snowflake_export_workflow_without_events(ateam, snowflake_batch_export, interval):
    workflow_id = str(uuid4())
    inputs = SnowflakeBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(snowflake_batch_export.id),
        data_interval_end="2023-03-20 14:40:00.000000",
        interval=interval,
        **snowflake_batch_export.destination.config,
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[SnowflakeBatchExportWorkflow],
            activities=[
                create_export_run,
                insert_into_snowflake_activity,
                update_export_run_status,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with responses.RequestsMock(
                target="snowflake.connector.vendored.requests.adapters.HTTPAdapter.send",
                assert_all_requests_are_fired=False,
            ) as rsps, override_settings(BATCH_EXPORT_SNOWFLAKE_UPLOAD_CHUNK_SIZE_BYTES=1**2):
                queries, staged_files = add_mock_snowflake_api(rsps)
                await activity_environment.client.execute_workflow(
                    SnowflakeBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

                assert contains_queries_in_order(
                    queries,
                )

                staged_data = "\n".join(staged_files)

                # Check that the data is correct.
                json_data = [json.loads(line) for line in staged_data.split("\n") if line]
                # Pull out the fields we inserted only
                json_data = [
                    {
                        "uuid": event["uuid"],
                        "event": event["event"],
                        "timestamp": event["timestamp"],
                        "properties": event["properties"],
                        "person_id": event["person_id"],
                    }
                    for event in json_data
                ]
                json_data.sort(key=lambda x: x["timestamp"])
                assert json_data == []

        runs = await afetch_batch_export_runs(batch_export_id=snowflake_batch_export.id)
        assert len(runs) == 1

        run = runs[0]
        assert run.status == "Completed"


async def test_snowflake_export_workflow_raises_error_on_put_fail(
    clickhouse_client, ateam, snowflake_batch_export, interval
):
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")
    data_interval_start = data_interval_end - snowflake_batch_export.interval_time_delta

    _ = await generate_test_events_in_clickhouse(
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

    inputs = SnowflakeBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(snowflake_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **snowflake_batch_export.destination.config,
    )

    workflow_id = str(uuid4())

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[SnowflakeBatchExportWorkflow],
            activities=[
                create_export_run,
                insert_into_snowflake_activity,
                update_export_run_status,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with responses.RequestsMock(
                target="snowflake.connector.vendored.requests.adapters.HTTPAdapter.send"
            ) as rsps, override_settings(BATCH_EXPORT_SNOWFLAKE_UPLOAD_CHUNK_SIZE_BYTES=1**2):
                add_mock_snowflake_api(rsps, fail="put")

                with pytest.raises(WorkflowFailureError) as exc_info:
                    await activity_environment.client.execute_workflow(
                        SnowflakeBatchExportWorkflow.run,
                        inputs,
                        id=workflow_id,
                        task_queue=settings.TEMPORAL_TASK_QUEUE,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )

                err = exc_info.value
                assert hasattr(err, "__cause__"), "Workflow failure missing cause"
                assert isinstance(err.__cause__, ActivityError)
                assert isinstance(err.__cause__.__cause__, ApplicationError)
                assert err.__cause__.__cause__.type == "SnowflakeFileNotUploadedError"


async def test_snowflake_export_workflow_raises_error_on_copy_fail(
    clickhouse_client, ateam, snowflake_batch_export, interval
):
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")
    data_interval_start = data_interval_end - snowflake_batch_export.interval_time_delta

    _ = await generate_test_events_in_clickhouse(
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

    inputs = SnowflakeBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(snowflake_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **snowflake_batch_export.destination.config,
    )

    workflow_id = str(uuid4())

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[SnowflakeBatchExportWorkflow],
            activities=[
                create_export_run,
                insert_into_snowflake_activity,
                update_export_run_status,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with responses.RequestsMock(
                target="snowflake.connector.vendored.requests.adapters.HTTPAdapter.send"
            ) as rsps, override_settings(BATCH_EXPORT_SNOWFLAKE_UPLOAD_CHUNK_SIZE_BYTES=1**2):
                add_mock_snowflake_api(rsps, fail="copy")

                with pytest.raises(WorkflowFailureError) as exc_info:
                    await activity_environment.client.execute_workflow(
                        SnowflakeBatchExportWorkflow.run,
                        inputs,
                        id=workflow_id,
                        task_queue=settings.TEMPORAL_TASK_QUEUE,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )

                err = exc_info.value
                assert hasattr(err, "__cause__"), "Workflow failure missing cause"
                assert isinstance(err.__cause__, ActivityError)
                assert isinstance(err.__cause__.__cause__, ApplicationError)
                assert err.__cause__.__cause__.type == "SnowflakeFileNotLoadedError"


async def test_snowflake_export_workflow_handles_insert_activity_errors(ateam, snowflake_batch_export):
    """Test that Snowflake Export Workflow can gracefully handle errors when inserting Snowflake data."""
    workflow_id = str(uuid4())
    inputs = SnowflakeBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(snowflake_batch_export.id),
        data_interval_end="2023-04-25 14:30:00.000000",
        **snowflake_batch_export.destination.config,
    )

    @activity.defn(name="insert_into_snowflake_activity")
    async def insert_into_snowflake_activity_mocked(_: SnowflakeInsertInputs) -> str:
        raise ValueError("A useful error message")

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[SnowflakeBatchExportWorkflow],
            activities=[
                create_export_run,
                insert_into_snowflake_activity_mocked,
                update_export_run_status,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await activity_environment.client.execute_workflow(
                    SnowflakeBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    runs = await afetch_batch_export_runs(batch_export_id=snowflake_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Failed"
    assert run.latest_error == "ValueError: A useful error message"


async def test_snowflake_export_workflow_handles_cancellation(ateam, snowflake_batch_export):
    """Test that Snowflake Export Workflow can gracefully handle cancellations when inserting Snowflake data."""
    workflow_id = str(uuid4())
    inputs = SnowflakeBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(snowflake_batch_export.id),
        data_interval_end="2023-04-25 14:30:00.000000",
        **snowflake_batch_export.destination.config,
    )

    @activity.defn(name="insert_into_snowflake_activity")
    async def never_finish_activity(_: SnowflakeInsertInputs) -> str:
        while True:
            activity.heartbeat()
            await asyncio.sleep(1)

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[SnowflakeBatchExportWorkflow],
            activities=[
                create_export_run,
                never_finish_activity,
                update_export_run_status,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await activity_environment.client.start_workflow(
                SnowflakeBatchExportWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=settings.TEMPORAL_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            await asyncio.sleep(5)
            await handle.cancel()

            with pytest.raises(WorkflowFailureError):
                await handle.result()

    runs = await afetch_batch_export_runs(batch_export_id=snowflake_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Cancelled"
    assert run.latest_error == "Cancelled"


def assert_events_in_snowflake(
    cursor: snowflake.connector.cursor.SnowflakeCursor, table_name: str, events: list, exclude_events: list[str]
):
    """Assert provided events are present in Snowflake table."""
    cursor.execute(f'SELECT * FROM "{table_name}"')

    rows = cursor.fetchall()

    columns = {index: metadata.name for index, metadata in enumerate(cursor.description)}
    json_columns = ("properties", "elements", "people_set", "people_set_once")

    # Rows are tuples, so we construct a dictionary using the metadata from cursor.description.
    # We rely on the order of the columns in each row matching the order set in cursor.description.
    # This seems to be the case, at least for now.
    inserted_events = [
        {
            columns[index]: json.loads(row[index])
            if columns[index] in json_columns and row[index] is not None
            else row[index]
            for index in columns.keys()
        }
        for row in rows
    ]
    inserted_events.sort(key=lambda x: (x["event"], x["timestamp"]))

    expected_events = []
    for event in events:
        event_name = event.get("event")

        if exclude_events is not None and event_name in exclude_events:
            continue

        properties = event.get("properties", None)
        elements_chain = event.get("elements_chain", None)
        expected_event = {
            "distinct_id": event.get("distinct_id"),
            "elements": json.dumps(elements_chain),
            "event": event_name,
            "ip": properties.get("$ip", None) if properties else None,
            "properties": event.get("properties"),
            "people_set": properties.get("$set", None) if properties else None,
            "people_set_once": properties.get("$set_once", None) if properties else None,
            "site_url": "",
            "timestamp": dt.datetime.fromisoformat(event.get("timestamp")),
            "team_id": event.get("team_id"),
            "uuid": event.get("uuid"),
        }
        expected_events.append(expected_event)

    expected_events.sort(key=lambda x: (x["event"], x["timestamp"]))

    assert inserted_events[0] == expected_events[0]
    assert inserted_events == expected_events


REQUIRED_ENV_VARS = (
    "SNOWFLAKE_WAREHOUSE",
    "SNOWFLAKE_PASSWORD",
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USERNAME",
)

SKIP_IF_MISSING_REQUIRED_ENV_VARS = pytest.mark.skipif(
    any(env_var not in os.environ for env_var in REQUIRED_ENV_VARS),
    reason="Snowflake required env vars are not set",
)


@pytest.fixture
def snowflake_cursor(snowflake_config):
    """Manage a snowflake cursor that cleans up after we are done."""
    with snowflake.connector.connect(
        user=snowflake_config["user"],
        password=snowflake_config["password"],
        account=snowflake_config["account"],
        warehouse=snowflake_config["warehouse"],
    ) as connection:
        cursor = connection.cursor()
        cursor.execute(f"CREATE DATABASE \"{snowflake_config['database']}\"")
        cursor.execute(f"CREATE SCHEMA \"{snowflake_config['database']}\".\"{snowflake_config['schema']}\"")
        cursor.execute(f"USE SCHEMA \"{snowflake_config['database']}\".\"{snowflake_config['schema']}\"")

        yield cursor

        cursor.execute(f"DROP DATABASE IF EXISTS \"{snowflake_config['database']}\" CASCADE")


@SKIP_IF_MISSING_REQUIRED_ENV_VARS
@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
async def test_insert_into_snowflake_activity_inserts_data_into_snowflake_table(
    clickhouse_client, activity_environment, snowflake_cursor, snowflake_config, exclude_events
):
    """Test that the insert_into_snowflake_activity function inserts data into a PostgreSQL table.

    We use the generate_test_events_in_clickhouse function to generate several sets
    of events. Some of these sets are expected to be exported, and others not. Expected
    events are those that:
    * Are created for the team_id of the batch export.
    * Are created in the date range of the batch export.
    * Are not duplicates of other events that are in the same batch.
    * Do not have an event name contained in the batch export's exclude_events.

    Once we have these events, we pass them to the assert_events_in_snowflake function to check
    that they appear in the expected Snowflake table. This function runs against a real Snowflake
    instance, so the environment should be populated with the necessary credentials.
    """
    data_interval_start = dt.datetime(2023, 4, 20, 14, 0, 0, tzinfo=dt.timezone.utc)
    data_interval_end = dt.datetime(2023, 4, 25, 15, 0, 0, tzinfo=dt.timezone.utc)

    team_id = random.randint(1, 1000000)
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

    events_to_exclude = []
    if exclude_events:
        for event_name in exclude_events:
            (events_to_exclude_for_event_name, _, _) = await generate_test_events_in_clickhouse(
                client=clickhouse_client,
                team_id=team_id,
                start_time=data_interval_start,
                end_time=data_interval_end,
                count=5,
                count_outside_range=0,
                count_other_team=0,
                event_name=event_name,
            )
            events_to_exclude += events_to_exclude_for_event_name

    table_name = f"test_insert_activity_table_{team_id}"
    insert_inputs = SnowflakeInsertInputs(
        team_id=team_id,
        table_name=table_name,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        **snowflake_config,
    )

    await activity_environment.run(insert_into_snowflake_activity, insert_inputs)

    assert_events_in_snowflake(
        cursor=snowflake_cursor,
        table_name=table_name,
        events=events + events_to_exclude,
        exclude_events=exclude_events,
    )


@SKIP_IF_MISSING_REQUIRED_ENV_VARS
@pytest.mark.parametrize("interval", ["hour", "day"], indirect=True)
@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
async def test_snowflake_export_workflow(
    clickhouse_client,
    snowflake_cursor,
    interval,
    snowflake_batch_export,
    ateam,
    exclude_events,
):
    """Test Redshift Export Workflow end-to-end.

    The workflow should update the batch export run status to completed and produce the expected
    records to the provided Redshift instance.
    """
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")
    data_interval_start = data_interval_end - snowflake_batch_export.interval_time_delta

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

    events_to_exclude = []
    if exclude_events:
        for event_name in exclude_events:
            (events_to_exclude_for_event_name, _, _) = await generate_test_events_in_clickhouse(
                client=clickhouse_client,
                team_id=ateam.pk,
                start_time=data_interval_start,
                end_time=data_interval_end,
                count=5,
                count_outside_range=0,
                count_other_team=0,
                event_name=event_name,
            )
            events_to_exclude += events_to_exclude_for_event_name

    workflow_id = str(uuid4())
    inputs = SnowflakeBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(snowflake_batch_export.id),
        data_interval_end="2023-04-25 14:30:00.000000",
        interval=interval,
        **snowflake_batch_export.destination.config,
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[SnowflakeBatchExportWorkflow],
            activities=[
                create_export_run,
                insert_into_snowflake_activity,
                update_export_run_status,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with override_settings(BATCH_EXPORT_REDSHIFT_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2):
                await activity_environment.client.execute_workflow(
                    SnowflakeBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=dt.timedelta(seconds=10),
                )

    runs = await afetch_batch_export_runs(batch_export_id=snowflake_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"

    assert_events_in_snowflake(
        cursor=snowflake_cursor,
        table_name=snowflake_batch_export.destination.config["table_name"],
        events=events + events_to_exclude,
        exclude_events=exclude_events,
    )
