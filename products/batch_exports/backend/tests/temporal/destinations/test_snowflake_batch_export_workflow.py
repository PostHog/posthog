import asyncio
import dataclasses
import datetime as dt
import gzip
import io
import json
import operator
import os
import re
import tempfile
import typing as t
import unittest.mock
import uuid
from collections import deque
from uuid import uuid4

import paramiko
import pytest
import pytest_asyncio
import responses
import snowflake.connector
from django.test import override_settings
from requests.models import PreparedRequest
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog import constants
from posthog.batch_exports.service import (
    BackfillDetails,
    BatchExportModel,
    BatchExportSchema,
)
from posthog.temporal.common.clickhouse import ClickHouseClient
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse
from posthog.temporal.tests.utils.models import (
    acreate_batch_export,
    adelete_batch_export,
    afetch_batch_export_runs,
)
from posthog.temporal.tests.utils.persons import (
    generate_test_person_distinct_id2_in_clickhouse,
    generate_test_persons_in_clickhouse,
)
from products.batch_exports.backend.temporal.batch_exports import (
    finish_batch_export_run,
    start_batch_export_run,
)
from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import (
    InvalidPrivateKeyError,
    SnowflakeBatchExportInputs,
    SnowflakeBatchExportWorkflow,
    SnowflakeHeartbeatDetails,
    SnowflakeInsertInputs,
    insert_into_snowflake_activity,
    load_private_key,
    snowflake_default_fields,
)
from products.batch_exports.backend.temporal.record_batch_model import SessionsRecordBatchModel
from products.batch_exports.backend.temporal.spmc import (
    Producer,
    RecordBatchQueue,
    RecordBatchTaskError,
)
from products.batch_exports.backend.tests.temporal.utils import (
    FlakyClickHouseClient,
    get_record_batch_from_queue,
    mocked_start_batch_export_run,
    remove_duplicates_from_records,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]

EXPECTED_PERSONS_BATCH_EXPORT_FIELDS = [
    "team_id",
    "distinct_id",
    "person_id",
    "properties",
    "person_version",
    "person_distinct_id_version",
    "created_at",
    "_inserted_at",
    "is_deleted",
]


TEST_TIME = dt.datetime.now(dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)


class FakeSnowflakeCursor:
    """A fake Snowflake cursor that can fail on PUT and COPY queries."""

    def __init__(self, *args, failure_mode: str | None = None, **kwargs):
        self._execute_calls: list[dict[str, t.Any]] = []
        self._execute_async_calls: list[dict[str, t.Any]] = []
        self._sfqid = 1
        self._fail = failure_mode

    @property
    def sfqid(self):
        current = self._sfqid
        self._sfqid += 1
        return current

    def execute(self, query, params=None, file_stream=None):
        self._execute_calls.append({"query": query, "params": params, "file_stream": file_stream})

    def execute_async(self, query, params=None, file_stream=None):
        self._execute_async_calls.append({"query": query, "params": params, "file_stream": file_stream})

    def get_results_from_sfqid(self, query_id):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args, **kwargs):
        pass

    def fetchone(self):
        if self._fail == "put":
            return (
                "test",
                "test.gz",
                456,
                0,
                "NONE",
                "GZIP",
                "FAILED",
                "Some error on put",
            )
        else:
            return (
                "test",
                "test.gz",
                456,
                0,
                "NONE",
                "GZIP",
                "UPLOADED",
                None,
            )

    def fetchall(self):
        if self._fail == "copy":
            return [("test", "LOAD FAILED", 100, 99, 1, 1, "Some error on copy", 3)]
        else:
            return [("test", "LOADED", 100, 99, 1, 1, "Some error on copy", 3)]

    def description(self):
        return []


class FakeSnowflakeConnection:
    def __init__(
        self,
        *args,
        failure_mode: str | None = None,
        **kwargs,
    ):
        self._cursors: list[FakeSnowflakeCursor] = []
        self._is_running = True
        self.failure_mode = failure_mode

    def cursor(self) -> FakeSnowflakeCursor:
        cursor = FakeSnowflakeCursor(failure_mode=self.failure_mode)
        self._cursors.append(cursor)
        return cursor

    def get_query_status_throw_if_error(self, query_id):
        return snowflake.connector.constants.QueryStatus.SUCCESS

    def is_still_running(self, status):
        current_status = self._is_running
        self._is_running = not current_status
        return current_status

    def close(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args, **kwargs):
        pass


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

        rowset: list[tuple[t.Any, ...]] = [("test", "LOADED", 456, 192, "NONE", "GZIP", "UPLOADED", "")]

        # If the query is something that looks like `PUT file:///tmp/tmp50nod7v9
        # @%"events"` we extract the /tmp/tmp50nod7v9 and store the file
        # contents as a string in `staged_files`.
        if match := re.match(r"^PUT file://(?P<file_path>.*) @%(?P<table_name>.*)$", sql_text):
            file_path = match.group("file_path")
            with open(file_path) as f:
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
                        "queryId": str(uuid4()),
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
    warehouse = os.getenv("SNOWFLAKE_WAREHOUSE", "warehouse")
    account = os.getenv("SNOWFLAKE_ACCOUNT", "account")
    role = os.getenv("SNOWFLAKE_ROLE", "role")
    username = os.getenv("SNOWFLAKE_USERNAME", "username")
    password = os.getenv("SNOWFLAKE_PASSWORD", "password")
    private_key = os.getenv("SNOWFLAKE_PRIVATE_KEY")
    private_key_passphrase = os.getenv("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE")

    config = {
        "user": username,
        "warehouse": warehouse,
        "account": account,
        "database": database,
        "schema": schema,
        "role": role,
    }
    if private_key:
        config["private_key"] = private_key
        config["private_key_passphrase"] = private_key_passphrase
        config["authentication_type"] = "keypair"
    elif password:
        config["password"] = password
        config["authentication_type"] = "password"
    else:
        raise ValueError("Either password or private key must be set")
    return config


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
async def test_snowflake_export_workflow_exports_events(
    ateam, clickhouse_client, database, schema, snowflake_batch_export, interval, table_name
):
    """Test that the whole workflow not just the activity works.

    It should update the batch export run status to completed, as well as updating the record
    count.
    """
    data_interval_end = dt.datetime.now(tz=dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    data_interval_end_str = data_interval_end.strftime("%Y-%m-%d_%H-%M-%S")
    data_interval_start = data_interval_end - snowflake_batch_export.interval_time_delta

    await generate_test_events_in_clickhouse(
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
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[SnowflakeBatchExportWorkflow],
            activities=[
                start_batch_export_run,
                insert_into_snowflake_activity,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with (
                unittest.mock.patch(
                    "products.batch_exports.backend.temporal.destinations.snowflake_batch_export.snowflake.connector.connect",
                ) as mock,
                override_settings(BATCH_EXPORT_SNOWFLAKE_UPLOAD_CHUNK_SIZE_BYTES=1),
            ):
                fake_conn = FakeSnowflakeConnection()
                mock.return_value = fake_conn

                await activity_environment.client.execute_workflow(
                    SnowflakeBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    execution_timeout=dt.timedelta(seconds=10),
                    task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

                execute_calls = []
                for cursor in fake_conn._cursors:
                    for call in cursor._execute_calls:
                        execute_calls.append(call["query"].strip())

                execute_async_calls = []
                for cursor in fake_conn._cursors:
                    for call in cursor._execute_async_calls:
                        execute_async_calls.append(call["query"].strip())

                assert execute_async_calls[0:3] == [
                    f'USE DATABASE "{database}"',
                    f'USE SCHEMA "{schema}"',
                    "SET ABORT_DETACHED_QUERY = FALSE",
                ]

                assert all(query.startswith("PUT") for query in execute_calls[0:9])

                assert execute_async_calls[3].startswith(f'CREATE TABLE IF NOT EXISTS "{table_name}"')
                assert execute_async_calls[4].startswith(f"""REMOVE '@%"{table_name}"/{data_interval_end_str}'""")
                assert execute_async_calls[5].startswith(f'COPY INTO "{table_name}"')

    runs = await afetch_batch_export_runs(batch_export_id=snowflake_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"
    assert run.records_completed == 10


@pytest.mark.parametrize("interval", ["hour", "day"], indirect=True)
async def test_snowflake_export_workflow_without_events(ateam, snowflake_batch_export, interval, truncate_events):
    workflow_id = str(uuid4())
    inputs = SnowflakeBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(snowflake_batch_export.id),
        data_interval_end=dt.datetime.now(tz=dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),
        interval=interval,
        **snowflake_batch_export.destination.config,
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[SnowflakeBatchExportWorkflow],
            activities=[
                start_batch_export_run,
                insert_into_snowflake_activity,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with (
                responses.RequestsMock(
                    target="snowflake.connector.vendored.requests.adapters.HTTPAdapter.send",
                    assert_all_requests_are_fired=False,
                ) as rsps,
                override_settings(BATCH_EXPORT_SNOWFLAKE_UPLOAD_CHUNK_SIZE_BYTES=1**2),
            ):
                queries, staged_files = add_mock_snowflake_api(rsps)
                await activity_environment.client.execute_workflow(
                    SnowflakeBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
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
    data_interval_end = dt.datetime.now(tz=dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
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
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[SnowflakeBatchExportWorkflow],
            activities=[
                start_batch_export_run,
                insert_into_snowflake_activity,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):

            class FakeSnowflakeConnectionFailOnPut(FakeSnowflakeConnection):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, failure_mode="put", **kwargs)

            with unittest.mock.patch(
                "products.batch_exports.backend.temporal.destinations.snowflake_batch_export.snowflake.connector.connect",
                side_effect=FakeSnowflakeConnectionFailOnPut,
            ):
                with pytest.raises(WorkflowFailureError) as exc_info:
                    await activity_environment.client.execute_workflow(
                        SnowflakeBatchExportWorkflow.run,
                        inputs,
                        id=workflow_id,
                        task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
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
    data_interval_end = dt.datetime.now(tz=dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
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
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[SnowflakeBatchExportWorkflow],
            activities=[
                start_batch_export_run,
                insert_into_snowflake_activity,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):

            class FakeSnowflakeConnectionFailOnCopy(FakeSnowflakeConnection):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, failure_mode="copy", **kwargs)

            with unittest.mock.patch(
                "products.batch_exports.backend.temporal.destinations.snowflake_batch_export.snowflake.connector.connect",
                side_effect=FakeSnowflakeConnectionFailOnCopy,
            ):
                with pytest.raises(WorkflowFailureError) as exc_info:
                    await activity_environment.client.execute_workflow(
                        SnowflakeBatchExportWorkflow.run,
                        inputs,
                        id=workflow_id,
                        task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
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
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[SnowflakeBatchExportWorkflow],
            activities=[
                mocked_start_batch_export_run,
                insert_into_snowflake_activity_mocked,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await activity_environment.client.execute_workflow(
                    SnowflakeBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    runs = await afetch_batch_export_runs(batch_export_id=snowflake_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "FailedRetryable"
    assert run.latest_error == "ValueError: A useful error message"
    assert run.records_completed is None


async def test_snowflake_export_workflow_handles_insert_activity_non_retryable_errors(ateam, snowflake_batch_export):
    """Test that Snowflake Export Workflow can gracefully handle non-retryable errors when inserting Snowflake data."""
    workflow_id = str(uuid4())
    inputs = SnowflakeBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(snowflake_batch_export.id),
        data_interval_end="2023-04-25 14:30:00.000000",
        **snowflake_batch_export.destination.config,
    )

    @activity.defn(name="insert_into_snowflake_activity")
    async def insert_into_snowflake_activity_mocked(_: SnowflakeInsertInputs) -> str:
        class ForbiddenError(Exception):
            pass

        raise ForbiddenError("A useful error message")

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[SnowflakeBatchExportWorkflow],
            activities=[
                mocked_start_batch_export_run,
                insert_into_snowflake_activity_mocked,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await activity_environment.client.execute_workflow(
                    SnowflakeBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    runs = await afetch_batch_export_runs(batch_export_id=snowflake_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Failed"
    assert run.latest_error == "ForbiddenError: A useful error message"
    assert run.records_completed is None


async def test_snowflake_export_workflow_handles_cancellation_mocked(ateam, snowflake_batch_export):
    """Test that Snowflake Export Workflow can gracefully handle cancellations when inserting Snowflake data.

    We mock the insert_into_snowflake_activity for this test.
    """
    data_interval_end = dt.datetime.now(dt.UTC)
    workflow_id = str(uuid4())
    inputs = SnowflakeBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(snowflake_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
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
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[SnowflakeBatchExportWorkflow],
            activities=[
                mocked_start_batch_export_run,
                never_finish_activity,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await activity_environment.client.start_workflow(
                SnowflakeBatchExportWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
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


async def assert_clickhouse_records_in_snowflake(
    snowflake_cursor: snowflake.connector.cursor.SnowflakeCursor,
    clickhouse_client: ClickHouseClient,
    table_name: str,
    team_id: int,
    data_interval_start: dt.datetime,
    data_interval_end: dt.datetime,
    exclude_events: list[str] | None = None,
    include_events: list[str] | None = None,
    batch_export_model: BatchExportModel | BatchExportSchema | None = None,
    backfill_details: BackfillDetails | None = None,
    sort_key: str = "event",
    expected_fields: list[str] | None = None,
    expect_duplicates: bool = False,
    primary_key: list[str] | None = None,
):
    """Assert ClickHouse records are written to Snowflake table.

    Arguments:
        snowflake_cursor: A SnowflakeCursor used to read records.
        clickhouse_client: A ClickHouseClient used to read records that are expected to be exported.
        team_id: The ID of the team that we are testing for.
        table_name: Snowflake table name where records are exported to.
        data_interval_start: Start of the batch period for exported records.
        data_interval_end: End of the batch period for exported records.
        exclude_events: Event names to be excluded from the export.
        include_events: Event names to be included in the export.
        batch_export_schema: Custom schema used in the batch export.
        expected_fields: List of fields expected to be in the destination table.
        expect_duplicates: Whether duplicates are expected (e.g. when testing retrying logic).
    """
    snowflake_cursor.execute(f'SELECT * FROM "{table_name}"')

    rows = snowflake_cursor.fetchall()

    columns = {index: metadata.name for index, metadata in enumerate(snowflake_cursor.description)}
    json_columns = ("properties", "person_properties", "people_set", "people_set_once", "urls")

    # Rows are tuples, so we construct a dictionary using the metadata from cursor.description.
    # We rely on the order of the columns in each row matching the order set in cursor.description.
    # This seems to be the case, at least for now.
    inserted_records = [
        {
            columns[index]: json.loads(row[index])
            if columns[index] in json_columns and row[index] is not None
            else row[index]
            for index in columns.keys()
        }
        for row in rows
    ]

    if batch_export_model is not None:
        if isinstance(batch_export_model, BatchExportModel):
            model_name = batch_export_model.name
            fields = batch_export_model.schema["fields"] if batch_export_model.schema is not None else None
            filters = batch_export_model.filters
            extra_query_parameters = (
                batch_export_model.schema["values"] if batch_export_model.schema is not None else None
            )
        else:
            model_name = "custom"
            fields = batch_export_model["fields"]
            filters = None
            extra_query_parameters = batch_export_model["values"]
    else:
        model_name = "events"
        extra_query_parameters = None
        fields = None
        filters = None

    expected_records = []
    queue = RecordBatchQueue()
    if model_name == "sessions":
        producer = Producer(model=SessionsRecordBatchModel(team_id))
    else:
        producer = Producer()

    producer_task = await producer.start(
        queue=queue,
        model_name=model_name,
        team_id=team_id,
        full_range=(data_interval_start, data_interval_end),
        done_ranges=[],
        fields=fields,
        filters=filters,
        destination_default_fields=snowflake_default_fields(),
        exclude_events=exclude_events,
        include_events=include_events,
        is_backfill=backfill_details is not None,
        backfill_details=backfill_details,
        extra_query_parameters=extra_query_parameters,
    )
    while True:
        record_batch = await get_record_batch_from_queue(queue, producer_task)

        if record_batch is None:
            break

        select = record_batch.column_names
        if expected_fields:
            select = expected_fields

        for record in record_batch.select(select).to_pylist():
            expected_record = {}

            for k, v in record.items():
                if k == "_inserted_at":
                    # _inserted_at is not exported, only used for tracking progress.
                    continue

                if k in json_columns and isinstance(v, str):
                    expected_record[k] = json.loads(v)
                elif isinstance(v, dt.datetime):
                    # By default, Snowflake's `TIMESTAMP` doesn't include a timezone component.
                    expected_record[k] = v.replace(tzinfo=None)
                elif k == "elements":
                    # Happens transparently when uploading elements as a variant field.
                    expected_record[k] = json.dumps(v)
                else:
                    expected_record[k] = v

            expected_records.append(expected_record)

    if expect_duplicates:
        inserted_records = remove_duplicates_from_records(inserted_records, primary_key)

    inserted_column_names = list(inserted_records[0].keys())
    expected_column_names = list(expected_records[0].keys())
    inserted_column_names.sort()
    expected_column_names.sort()

    # Ordering is not guaranteed, so we sort before comparing.
    inserted_records.sort(key=operator.itemgetter(sort_key))
    expected_records.sort(key=operator.itemgetter(sort_key))

    assert inserted_column_names == expected_column_names
    assert len(inserted_records) == len(expected_records)
    assert inserted_records[0] == expected_records[0]
    assert inserted_records == expected_records
    assert len(inserted_column_names) > 0


REQUIRED_ENV_VARS = (
    "SNOWFLAKE_WAREHOUSE",
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USERNAME",
)


def snowflake_env_vars_are_set():
    if not all(env_var in os.environ for env_var in REQUIRED_ENV_VARS):
        return False
    if "SNOWFLAKE_PASSWORD" not in os.environ and "SNOWFLAKE_PRIVATE_KEY" not in os.environ:
        return False
    return True


SKIP_IF_MISSING_REQUIRED_ENV_VARS = pytest.mark.skipif(
    not snowflake_env_vars_are_set(),
    reason="Snowflake required env vars are not set",
)


@pytest.fixture
def snowflake_cursor(snowflake_config):
    """Manage a snowflake cursor that cleans up after we are done."""
    password = None
    private_key = None
    if snowflake_config["authentication_type"] == "keypair":
        if snowflake_config.get("private_key") is None:
            raise ValueError("Private key is required for keypair authentication")

        private_key = load_private_key(snowflake_config["private_key"], snowflake_config["private_key_passphrase"])
    else:
        password = snowflake_config["password"]

    with snowflake.connector.connect(
        user=snowflake_config["user"],
        password=password,
        role=snowflake_config["role"],
        account=snowflake_config["account"],
        warehouse=snowflake_config["warehouse"],
        private_key=private_key,
    ) as connection:
        connection.telemetry_enabled = False
        cursor = connection.cursor()
        cursor.execute(f'CREATE DATABASE "{snowflake_config["database"]}"')
        cursor.execute(f'CREATE SCHEMA "{snowflake_config["database"]}"."{snowflake_config["schema"]}"')
        cursor.execute(f'USE SCHEMA "{snowflake_config["database"]}"."{snowflake_config["schema"]}"')

        yield cursor

        cursor.execute(f'DROP DATABASE IF EXISTS "{snowflake_config["database"]}" CASCADE')


TEST_MODELS: list[BatchExportModel | BatchExportSchema | None] = [
    BatchExportModel(
        name="a-custom-model",
        schema={
            "fields": [
                {"expression": "event", "alias": "event"},
                {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_0)s), '')", "alias": "browser"},
                {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_1)s), '')", "alias": "os"},
                {"expression": "nullIf(properties, '')", "alias": "all_properties"},
            ],
            "values": {"hogql_val_0": "$browser", "hogql_val_1": "$os"},
        },
    ),
    BatchExportModel(name="events", schema=None),
    BatchExportModel(name="persons", schema=None),
    BatchExportModel(name="sessions", schema=None),
    {
        "fields": [
            {"expression": "event", "alias": "event"},
            {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_0)s), '')", "alias": "browser"},
            {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_1)s), '')", "alias": "os"},
            {"expression": "nullIf(properties, '')", "alias": "all_properties"},
        ],
        "values": {"hogql_val_0": "$browser", "hogql_val_1": "$os"},
    },
    None,
]


@SKIP_IF_MISSING_REQUIRED_ENV_VARS
@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
@pytest.mark.parametrize("model", TEST_MODELS)
async def test_insert_into_snowflake_activity_inserts_data_into_snowflake_table(
    clickhouse_client,
    activity_environment,
    snowflake_cursor,
    snowflake_config,
    exclude_events,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
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
    if isinstance(model, BatchExportModel) and model.name == "persons" and exclude_events is not None:
        pytest.skip("Unnecessary test case as person batch export is not affected by 'exclude_events'")

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    table_name = f"test_insert_activity_table_{ateam.pk}"
    insert_inputs = SnowflakeInsertInputs(
        team_id=ateam.pk,
        table_name=table_name,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        **snowflake_config,
    )

    await activity_environment.run(insert_into_snowflake_activity, insert_inputs)

    sort_key = "event"
    if batch_export_model is not None:
        if batch_export_model.name == "persons":
            sort_key = "person_id"
        elif batch_export_model.name == "sessions":
            sort_key = "session_id"

    await assert_clickhouse_records_in_snowflake(
        snowflake_cursor=snowflake_cursor,
        clickhouse_client=clickhouse_client,
        table_name=table_name,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        exclude_events=exclude_events,
        batch_export_model=model,
        sort_key=sort_key,
    )


@SKIP_IF_MISSING_REQUIRED_ENV_VARS
async def test_insert_into_snowflake_activity_merges_persons_data_in_follow_up_runs(
    clickhouse_client,
    activity_environment,
    snowflake_cursor,
    snowflake_config,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
):
    """Test that the `insert_into_snowflake_activity` merges new versions of person rows.

    This unit tests looks at the mutability handling capabilities of the aforementioned activity.
    We will generate a new entry in the persons table for half of the persons exported in a first
    run of the activity. We expect the new entries to have replaced the old ones in Snowflake after
    the second run.
    """
    model = BatchExportModel(name="persons", schema=None)

    table_name = f"test_insert_activity_table_mutable_persons_{ateam.pk}"
    insert_inputs = SnowflakeInsertInputs(
        team_id=ateam.pk,
        table_name=table_name,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        batch_export_model=model,
        **snowflake_config,
    )

    await activity_environment.run(insert_into_snowflake_activity, insert_inputs)

    await assert_clickhouse_records_in_snowflake(
        snowflake_cursor=snowflake_cursor,
        clickhouse_client=clickhouse_client,
        table_name=table_name,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        sort_key="person_id",
    )

    _, persons_to_export_created = generate_test_data

    for old_person in persons_to_export_created[: len(persons_to_export_created) // 2]:
        new_person_id = uuid.uuid4()
        new_person, _ = await generate_test_persons_in_clickhouse(
            client=clickhouse_client,
            team_id=ateam.pk,
            start_time=data_interval_start,
            end_time=data_interval_end,
            person_id=new_person_id,
            count=1,
            properties={"utm_medium": "referral", "$initial_os": "Linux", "new_property": "Something"},
        )

        await generate_test_person_distinct_id2_in_clickhouse(
            clickhouse_client,
            ateam.pk,
            person_id=uuid.UUID(new_person[0]["id"]),
            distinct_id=old_person["distinct_id"],
            version=old_person["version"] + 1,
            timestamp=old_person["_timestamp"],
        )

    await activity_environment.run(insert_into_snowflake_activity, insert_inputs)

    await assert_clickhouse_records_in_snowflake(
        snowflake_cursor=snowflake_cursor,
        clickhouse_client=clickhouse_client,
        table_name=table_name,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        sort_key="person_id",
    )


@SKIP_IF_MISSING_REQUIRED_ENV_VARS
async def test_insert_into_snowflake_activity_merges_sessions_data_in_follow_up_runs(
    clickhouse_client,
    activity_environment,
    snowflake_cursor,
    snowflake_config,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
):
    """Test that the `insert_into_snowflake_activity` merges new versions of sessions rows.

    This unit tests looks at the mutability handling capabilities of the aforementioned activity.
    We will generate a new entry in the raw_sessions table for the one session exported in the first
    run of the activity. We expect the new entries to have replaced the old ones in Snowflake after
    the second run with the same time range.
    """
    model = BatchExportModel(name="sessions", schema=None)

    table_name = f"test_insert_activity_table_mutable_sessions_{ateam.pk}"
    insert_inputs = SnowflakeInsertInputs(
        team_id=ateam.pk,
        table_name=table_name,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        batch_export_model=model,
        **snowflake_config,
    )

    await activity_environment.run(insert_into_snowflake_activity, insert_inputs)

    await assert_clickhouse_records_in_snowflake(
        snowflake_cursor=snowflake_cursor,
        clickhouse_client=clickhouse_client,
        table_name=table_name,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        sort_key="session_id",
    )

    events_to_export_created, _ = generate_test_data
    event = events_to_export_created[0]

    new_data_interval_start, new_data_interval_end = (
        data_interval_start + dt.timedelta(hours=1),
        data_interval_end + dt.timedelta(hours=1),
    )

    new_events, _, _ = await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=ateam.pk,
        start_time=new_data_interval_start,
        end_time=new_data_interval_end,
        count=1,
        count_outside_range=0,
        count_other_team=0,
        duplicate=False,
        properties=event["properties"],
        person_properties={"utm_medium": "referral", "$initial_os": "Linux"},
        event_name=event["event"],
        table="sharded_events",
        insert_sessions=True,
    )

    insert_inputs.data_interval_start = new_data_interval_start.isoformat()
    insert_inputs.data_interval_end = new_data_interval_end.isoformat()

    await activity_environment.run(insert_into_snowflake_activity, insert_inputs)

    await assert_clickhouse_records_in_snowflake(
        snowflake_cursor=snowflake_cursor,
        clickhouse_client=clickhouse_client,
        table_name=table_name,
        team_id=ateam.pk,
        data_interval_start=new_data_interval_start,
        data_interval_end=new_data_interval_end,
        batch_export_model=model,
        sort_key="session_id",
    )

    snowflake_cursor.execute(f'SELECT "session_id", "end_timestamp" FROM "{table_name}"')
    rows = list(snowflake_cursor.fetchall())
    new_event = new_events[0]
    new_event_properties = new_event["properties"] or {}
    assert len(rows) == 1
    assert rows[0][0] == new_event_properties["$session_id"]
    assert rows[0][1] == dt.datetime.fromisoformat(new_event["timestamp"])


@pytest.fixture
def garbage_jsonl_file():
    """Manage a JSON file with garbage data."""
    with tempfile.NamedTemporaryFile("w+b", suffix=".jsonl", prefix="garbage_") as garbage_jsonl_file:
        garbage_jsonl_file.write(b'{"team_id": totally not an integer}\n')
        garbage_jsonl_file.seek(0)

        yield garbage_jsonl_file.name


@SKIP_IF_MISSING_REQUIRED_ENV_VARS
async def test_insert_into_snowflake_activity_removes_internal_stage_files(
    clickhouse_client,
    activity_environment,
    snowflake_cursor,
    snowflake_config,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
    garbage_jsonl_file,
):
    """Test that the `insert_into_snowflake_activity` removes internal stage files.

    This test requires some setup steps:
    1. We do a first run of the activity to create the export table. Since we
        haven't added any garbage, this should work normally.
    2. Truncate the table to avoid duplicate data once we re-run the activity.
    3. PUT a file with garbage data into the table internal stage.

    Once we run the activity a second time, it should first clear up the garbage
    file and not fail the COPY. After this second execution is done, and besides
    checking this second run worked and exported data, we also check that no files
    are present in the table's internal stage.
    """
    model = BatchExportModel(name="events", schema=None)

    table_name = f"test_insert_activity_table_remove_{ateam.pk}"

    insert_inputs = SnowflakeInsertInputs(
        team_id=ateam.pk,
        table_name=table_name,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        batch_export_model=model,
        **snowflake_config,
    )

    await activity_environment.run(insert_into_snowflake_activity, insert_inputs)

    await assert_clickhouse_records_in_snowflake(
        snowflake_cursor=snowflake_cursor,
        clickhouse_client=clickhouse_client,
        table_name=table_name,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        sort_key="event",
    )

    snowflake_cursor.execute(f'TRUNCATE TABLE "{table_name}"')

    data_interval_end_str = data_interval_end.strftime("%Y-%m-%d_%H-%M-%S")

    put_query = f"""
    PUT file://{garbage_jsonl_file} '@%"{table_name}"/{data_interval_end_str}'
    """
    snowflake_cursor.execute(put_query)

    list_query = f"""
    LIST '@%"{table_name}"'
    """
    snowflake_cursor.execute(list_query)
    rows = snowflake_cursor.fetchall()
    columns = {index: metadata.name for index, metadata in enumerate(snowflake_cursor.description)}
    stage_files = [{columns[index]: row[index] for index in columns.keys()} for row in rows]
    assert len(stage_files) == 1
    assert stage_files[0]["name"] == f"{data_interval_end_str}/{os.path.basename(garbage_jsonl_file)}.gz"

    await activity_environment.run(insert_into_snowflake_activity, insert_inputs)

    await assert_clickhouse_records_in_snowflake(
        snowflake_cursor=snowflake_cursor,
        clickhouse_client=clickhouse_client,
        table_name=table_name,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        sort_key="event",
    )

    snowflake_cursor.execute(list_query)
    rows = snowflake_cursor.fetchall()
    assert len(rows) == 0


@SKIP_IF_MISSING_REQUIRED_ENV_VARS
@pytest.mark.parametrize("interval", ["hour", "day"], indirect=True)
@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
@pytest.mark.parametrize("model", TEST_MODELS)
async def test_snowflake_export_workflow(
    clickhouse_client,
    snowflake_cursor,
    interval,
    snowflake_batch_export,
    ateam,
    exclude_events,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
    data_interval_start,
    data_interval_end,
):
    """Test Redshift Export Workflow end-to-end.

    The workflow should update the batch export run status to completed and produce the expected
    records to the provided Redshift instance.
    """
    if isinstance(model, BatchExportModel) and model.name == "persons" and exclude_events is not None:
        pytest.skip("Unnecessary test case as person batch export is not affected by 'exclude_events'")

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    workflow_id = str(uuid4())
    inputs = SnowflakeBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(snowflake_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        **snowflake_batch_export.destination.config,
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[SnowflakeBatchExportWorkflow],
            activities=[
                start_batch_export_run,
                insert_into_snowflake_activity,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await activity_environment.client.execute_workflow(
                SnowflakeBatchExportWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
                execution_timeout=dt.timedelta(minutes=2),
            )

    runs = await afetch_batch_export_runs(batch_export_id=snowflake_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"

    sort_key = "event"
    if batch_export_model is not None:
        if batch_export_model.name == "persons":
            sort_key = "person_id"
        elif batch_export_model.name == "sessions":
            sort_key = "session_id"

    await assert_clickhouse_records_in_snowflake(
        snowflake_cursor=snowflake_cursor,
        clickhouse_client=clickhouse_client,
        table_name=snowflake_batch_export.destination.config["table_name"],
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        exclude_events=exclude_events,
        batch_export_model=model,
        sort_key=sort_key,
    )


@SKIP_IF_MISSING_REQUIRED_ENV_VARS
@pytest.mark.parametrize("interval", ["hour", "day"], indirect=True)
@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
@pytest.mark.parametrize("model", TEST_MODELS)
async def test_snowflake_export_workflow_with_many_files(
    clickhouse_client,
    snowflake_cursor,
    interval,
    snowflake_batch_export,
    ateam,
    exclude_events,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
    data_interval_start,
    data_interval_end,
):
    """Test Snowflake Export Workflow end-to-end with multiple file uploads.

    This test overrides the chunk size and sets it to 1 byte to trigger multiple file uploads.
    We want to assert that all files are properly copied into the table. Of course, 1 byte limit
    means we are uploading one file at a time, which is very innefficient. For this reason, this test
    can take longer, so we keep the event count low and bump the Workflow timeout.
    """
    if isinstance(model, BatchExportModel) and model.name == "persons" and exclude_events is not None:
        pytest.skip("Unnecessary test case as person batch export is not affected by 'exclude_events'")

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    workflow_id = str(uuid4())
    inputs = SnowflakeBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(snowflake_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        **snowflake_batch_export.destination.config,
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[SnowflakeBatchExportWorkflow],
            activities=[
                start_batch_export_run,
                insert_into_snowflake_activity,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with override_settings(BATCH_EXPORT_SNOWFLAKE_UPLOAD_CHUNK_SIZE_BYTES=1):
                await activity_environment.client.execute_workflow(
                    SnowflakeBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=dt.timedelta(minutes=2),
                )

    runs = await afetch_batch_export_runs(batch_export_id=snowflake_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"

    sort_key = "event"
    if batch_export_model is not None:
        if batch_export_model.name == "persons":
            sort_key = "person_id"
        elif batch_export_model.name == "sessions":
            sort_key = "session_id"

    await assert_clickhouse_records_in_snowflake(
        snowflake_cursor=snowflake_cursor,
        clickhouse_client=clickhouse_client,
        table_name=snowflake_batch_export.destination.config["table_name"],
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        exclude_events=exclude_events,
        batch_export_model=model,
        sort_key=sort_key,
    )


@SKIP_IF_MISSING_REQUIRED_ENV_VARS
@pytest.mark.parametrize(
    "data_interval_start",
    # This is set to 24 hours before the `data_interval_end` to ensure that the data created is outside the batch
    # interval.
    [TEST_TIME - dt.timedelta(hours=24)],
    indirect=True,
)
@pytest.mark.parametrize("interval", ["hour"], indirect=True)
@pytest.mark.parametrize("model", [BatchExportModel(name="persons", schema=None)])
async def test_snowflake_export_workflow_backfill_earliest_persons(
    ateam,
    clickhouse_client,
    data_interval_start,
    data_interval_end,
    generate_test_data,
    interval,
    model,
    snowflake_batch_export,
    snowflake_cursor,
):
    """Test a `SnowflakeBatchExportWorkflow` backfilling the persons model.

    We expect persons outside the batch interval to also be backfilled (i.e. persons that were updated
    more than an hour ago) when setting `is_earliest_backfill=True`.
    """
    workflow_id = str(uuid.uuid4())
    inputs = SnowflakeBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(snowflake_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_model=model,
        backfill_details=BackfillDetails(
            backfill_id=None,
            is_earliest_backfill=True,
            start_at=None,
            end_at=data_interval_end.isoformat(),
        ),
        **snowflake_batch_export.destination.config,
    )
    _, persons = generate_test_data

    # Ensure some data outside batch interval has been created
    assert any(
        data_interval_end - person["_timestamp"].replace(tzinfo=dt.UTC) > dt.timedelta(hours=12) for person in persons
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[SnowflakeBatchExportWorkflow],
            activities=[
                start_batch_export_run,
                insert_into_snowflake_activity,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with override_settings(BATCH_EXPORT_SNOWFLAKE_UPLOAD_CHUNK_SIZE_BYTES=1):
                await activity_environment.client.execute_workflow(
                    SnowflakeBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=dt.timedelta(minutes=10),
                )

    runs = await afetch_batch_export_runs(batch_export_id=snowflake_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"
    assert run.data_interval_start is None

    await assert_clickhouse_records_in_snowflake(
        snowflake_cursor=snowflake_cursor,
        clickhouse_client=clickhouse_client,
        table_name=snowflake_batch_export.destination.config["table_name"],
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        sort_key="person_id",
    )


@SKIP_IF_MISSING_REQUIRED_ENV_VARS
async def test_snowflake_export_workflow_handles_cancellation(
    clickhouse_client, ateam, snowflake_batch_export, interval, snowflake_cursor
):
    """Test that Snowflake Export Workflow can gracefully handle cancellations when inserting Snowflake data."""
    data_interval_end = dt.datetime.now(dt.UTC)
    data_interval_start = data_interval_end - snowflake_batch_export.interval_time_delta

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
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[SnowflakeBatchExportWorkflow],
            activities=[
                start_batch_export_run,
                insert_into_snowflake_activity,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            # We set the chunk size low on purpose to slow things down and give us time to cancel.
            with override_settings(BATCH_EXPORT_SNOWFLAKE_UPLOAD_CHUNK_SIZE_BYTES=1):
                handle = await activity_environment.client.start_workflow(
                    SnowflakeBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

            # We need to wait a bit for the activity to start running.
            await asyncio.sleep(5)
            await handle.cancel()

            with pytest.raises(WorkflowFailureError):
                await handle.result()

    runs = await afetch_batch_export_runs(batch_export_id=snowflake_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Cancelled"
    assert run.latest_error == "Cancelled"


@SKIP_IF_MISSING_REQUIRED_ENV_VARS
async def test_insert_into_snowflake_activity_heartbeats(
    clickhouse_client,
    ateam,
    snowflake_batch_export,
    snowflake_cursor,
    snowflake_config,
    activity_environment,
):
    """Test that the insert_into_snowflake_activity activity sends heartbeats.

    We use a function that runs on_heartbeat to check and track the heartbeat contents.
    """
    data_interval_end = dt.datetime.now(dt.UTC)
    data_interval_start = data_interval_end - snowflake_batch_export.interval_time_delta

    n_expected_files = 3

    for n_expected_file in range(1, n_expected_files + 1):
        part_inserted_at = data_interval_end - snowflake_batch_export.interval_time_delta / n_expected_file

        await generate_test_events_in_clickhouse(
            client=clickhouse_client,
            team_id=ateam.pk,
            start_time=data_interval_start,
            end_time=data_interval_end,
            count=1,
            count_outside_range=0,
            count_other_team=0,
            duplicate=False,
            inserted_at=part_inserted_at,
            event_name=f"test-event-{n_expected_file}-{{i}}",
        )

    captured_details = []

    def capture_heartbeat_details(*details):
        """A function to track what we heartbeat."""
        nonlocal captured_details

        captured_details.append(details)

    activity_environment.on_heartbeat = capture_heartbeat_details

    table_name = f"test_insert_activity_table_{ateam.pk}"
    insert_inputs = SnowflakeInsertInputs(
        team_id=ateam.pk,
        table_name=table_name,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        **snowflake_config,
    )

    with override_settings(BATCH_EXPORT_SNOWFLAKE_UPLOAD_CHUNK_SIZE_BYTES=0):
        await activity_environment.run(insert_into_snowflake_activity, insert_inputs)

    # It's not guaranteed we will heartbeat right after every file.
    assert len(captured_details) > 0

    await assert_clickhouse_records_in_snowflake(
        snowflake_cursor=snowflake_cursor,
        clickhouse_client=clickhouse_client,
        table_name=table_name,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        sort_key="event",
    )


@pytest.mark.parametrize(
    "details",
    [
        ([(dt.datetime.now().isoformat(), dt.datetime.now().isoformat())], 10, 1),
        (
            [(dt.datetime.now().isoformat(), dt.datetime.now().isoformat())],
            10,
        ),
    ],
)
def test_snowflake_heartbeat_details_parses_from_tuple(details):
    class FakeActivity:
        def info(self):
            return FakeInfo()

    class FakeInfo:
        def __init__(self):
            self.heartbeat_details = details

    snowflake_details = SnowflakeHeartbeatDetails.from_activity(FakeActivity())
    expected_done_ranges = details[0]

    assert snowflake_details.done_ranges == [
        (
            dt.datetime.fromisoformat(expected_done_ranges[0][0]),
            dt.datetime.fromisoformat(expected_done_ranges[0][1]),
        )
    ]


@SKIP_IF_MISSING_REQUIRED_ENV_VARS
async def test_insert_into_snowflake_activity_handles_person_schema_changes(
    clickhouse_client,
    activity_environment,
    snowflake_cursor,
    snowflake_config,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
):
    """Test that the `insert_into_snowflake_activity` handles changes to the
    person schema.

    If we update the schema of the persons model we export, we should still be
    able to export the data without breaking existing exports. For example, any
    new fields should not be added to the destination (in future we may want to
    allow this but for now we don't).

    To replicate this situation we first export the data with the original
    schema, then delete a column in the destination and then rerun the export.
    """
    model = BatchExportModel(name="persons", schema=None)

    table_name = f"test_insert_activity_migration_table_{ateam.pk}"
    insert_inputs = SnowflakeInsertInputs(
        team_id=ateam.pk,
        table_name=table_name,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        batch_export_model=model,
        **snowflake_config,
    )

    await activity_environment.run(insert_into_snowflake_activity, insert_inputs)

    await assert_clickhouse_records_in_snowflake(
        snowflake_cursor=snowflake_cursor,
        clickhouse_client=clickhouse_client,
        table_name=table_name,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        sort_key="person_id",
    )

    # Drop the created_at column from the Snowflake table
    snowflake_cursor.execute(f'ALTER TABLE "{table_name}" DROP COLUMN "created_at"')

    _, persons_to_export_created = generate_test_data

    for old_person in persons_to_export_created[: len(persons_to_export_created) // 2]:
        new_person_id = uuid.uuid4()
        new_person, _ = await generate_test_persons_in_clickhouse(
            client=clickhouse_client,
            team_id=ateam.pk,
            start_time=data_interval_start,
            end_time=data_interval_end,
            person_id=new_person_id,
            count=1,
            properties={"utm_medium": "referral", "$initial_os": "Linux", "new_property": "Something"},
        )

        await generate_test_person_distinct_id2_in_clickhouse(
            clickhouse_client,
            ateam.pk,
            person_id=uuid.UUID(new_person[0]["id"]),
            distinct_id=old_person["distinct_id"],
            version=old_person["version"] + 1,
            timestamp=old_person["_timestamp"],
        )

    await activity_environment.run(insert_into_snowflake_activity, insert_inputs)

    # This time we don't expect there to be a created_at column
    expected_fields = [field for field in EXPECTED_PERSONS_BATCH_EXPORT_FIELDS if field != "created_at"]
    await assert_clickhouse_records_in_snowflake(
        snowflake_cursor=snowflake_cursor,
        clickhouse_client=clickhouse_client,
        table_name=table_name,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        sort_key="person_id",
        expected_fields=expected_fields,
    )


def test_load_private_key_raises_error_if_key_is_invalid():
    with pytest.raises(InvalidPrivateKeyError):
        load_private_key("invalid_key", None)


def test_load_private_key_raises_error_if_incorrect_passphrase():
    """Test we raise the right error when passing an incorrect passphrase."""
    key = paramiko.RSAKey.generate(2048)
    buffer = io.StringIO()
    key.write_private_key(buffer, password="a-passphrase")
    _ = buffer.seek(0)

    with pytest.raises(InvalidPrivateKeyError) as exc_info:
        _ = load_private_key(buffer.read(), "another-passphrase")

    assert "incorrect passphrase" in str(exc_info.value)


def test_load_private_key_raises_error_if_passphrase_not_empty():
    """Test we raise the right error when passing a passphrase to a key without one."""
    key = paramiko.RSAKey.generate(2048)
    buffer = io.StringIO()
    key.write_private_key(buffer)
    _ = buffer.seek(0)

    with pytest.raises(InvalidPrivateKeyError) as exc_info:
        _ = load_private_key(buffer.read(), "a-passphrase")

    assert "passphrase was given but private key is not encrypted" in str(exc_info.value)


def test_load_private_key_raises_error_if_passphrase_missing():
    """Test we raise the right error when missing a passphrase to an encrypted key."""
    key = paramiko.RSAKey.generate(2048)
    buffer = io.StringIO()
    key.write_private_key(buffer, password="a-passphrase")
    _ = buffer.seek(0)

    with pytest.raises(InvalidPrivateKeyError) as exc_info:
        _ = load_private_key(buffer.read(), None)

    assert "passphrase was not given but private key is encrypted" in str(exc_info.value)


def test_load_private_key_passes_with_empty_passphrase_and_no_encryption():
    """Test we succeed in loading a passphrase without encryption and an empty passphrase."""
    key = paramiko.RSAKey.generate(2048)
    buffer = io.StringIO()
    key.write_private_key(buffer, password=None)
    _ = buffer.seek(0)

    loaded = load_private_key(buffer.read(), "")

    assert loaded


@pytest.mark.parametrize("passphrase", ["a-passphrase", None, ""])
def test_load_private_key(passphrase: str | None):
    """Test we can load a private key.

    We treat `None` and empty string the same (no passphrase) because paramiko does
    not support passphrases smaller than 1 byte.
    """
    key = paramiko.RSAKey.generate(2048)
    buffer = io.StringIO()
    key.write_private_key(buffer, password=None if passphrase is None or passphrase == "" else passphrase)
    _ = buffer.seek(0)
    private_key = buffer.read()

    # Just checking this doesn't fail.
    loaded = load_private_key(private_key, passphrase)
    assert loaded


@SKIP_IF_MISSING_REQUIRED_ENV_VARS
@pytest.mark.parametrize(
    "model", [BatchExportModel(name="events", schema=None), BatchExportModel(name="persons", schema=None)]
)
async def test_insert_into_snowflake_activity_completes_range_when_there_is_a_failure(
    clickhouse_client,
    activity_environment,
    snowflake_cursor,
    snowflake_config,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
    model,
):
    """Test that the insert_into_snowflake_activity can resume from a failure using heartbeat details."""
    table_name = f"test_insert_activity_table_{ateam.pk}"

    events_to_create, persons_to_create = generate_test_data
    total_records = len(persons_to_create) if model.name == "persons" else len(events_to_create)
    # fail halfway through
    fail_after_records = total_records // 2

    heartbeat_details: list[SnowflakeHeartbeatDetails] = []

    def track_hearbeat_details(*details):
        """Record heartbeat details received."""
        nonlocal heartbeat_details
        snowflake_details = SnowflakeHeartbeatDetails.from_activity_details(details)
        heartbeat_details.append(snowflake_details)

    activity_environment.on_heartbeat = track_hearbeat_details

    insert_inputs = SnowflakeInsertInputs(
        team_id=ateam.pk,
        table_name=table_name,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        batch_export_model=model,
        **snowflake_config,
    )

    with unittest.mock.patch(
        "posthog.temporal.common.clickhouse.ClickHouseClient",
        lambda *args, **kwargs: FlakyClickHouseClient(*args, **kwargs, fail_after_records=fail_after_records),
    ):
        # We expect this to raise an exception
        with pytest.raises(RecordBatchTaskError):
            await activity_environment.run(insert_into_snowflake_activity, insert_inputs)

    assert len(heartbeat_details) > 0
    detail = heartbeat_details[-1]
    assert len(detail.done_ranges) > 0
    assert detail.records_completed == fail_after_records

    # Now we resume from the heartbeat
    previous_info = dataclasses.asdict(activity_environment.info)
    previous_info["heartbeat_details"] = detail.serialize_details()
    new_info = activity.Info(
        **previous_info,
    )

    activity_environment.info = new_info

    await activity_environment.run(insert_into_snowflake_activity, insert_inputs)

    assert len(heartbeat_details) > 0
    detail = heartbeat_details[-1]
    assert len(detail.done_ranges) == 1
    assert detail.done_ranges[0] == (data_interval_start, data_interval_end)

    sort_key = "event" if model.name == "events" else "person_id"

    # Verify all the data for the whole range was exported correctly
    await assert_clickhouse_records_in_snowflake(
        snowflake_cursor=snowflake_cursor,
        clickhouse_client=clickhouse_client,
        table_name=table_name,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        sort_key=sort_key,
        batch_export_model=model,
        expect_duplicates=True,
        primary_key=["uuid"] if model.name == "events" else ["distinct_id", "person_id"],
    )
