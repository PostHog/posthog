import datetime as dt
import gzip
import json
import re
from collections import deque
from uuid import uuid4

import pytest
import responses
from django.conf import settings
from django.test import override_settings
from requests.models import PreparedRequest
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.api.test.test_organization import acreate_organization
from posthog.api.test.test_team import acreate_team
from posthog.temporal.tests.batch_exports.base import (
    EventValues,
    insert_events,
)
from posthog.temporal.tests.batch_exports.fixtures import (
    acreate_batch_export,
    afetch_batch_export_runs,
)
from posthog.temporal.workflows.base import create_export_run, update_export_run_status
from posthog.temporal.workflows.clickhouse import ClickHouseClient
from posthog.temporal.workflows.snowflake_batch_export import (
    SnowflakeBatchExportInputs,
    SnowflakeBatchExportWorkflow,
    insert_into_snowflake_activity,
)


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
                rowset = [("test", "test.gz", 456, 0, "NONE", "GZIP", "FAILED", "Some error on put")]

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
            "data": {"token": "test-token", "masterToken": "test-token", "code": None, "message": None},
        },
    )
    rsps.add_callback(
        responses.POST,
        "https://account.snowflakecomputing.com:443/queries/v1/query-request",
        callback=query_request_handler,
    )

    return queries, staged_files


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_snowflake_export_workflow_exports_events_in_the_last_hour_for_the_right_team():
    """Test that the whole workflow not just the activity works.

    It should update the batch export run status to completed, as well as updating the record
    count.
    """
    ch_client = ClickHouseClient(
        url=settings.CLICKHOUSE_HTTP_URL,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
    )

    destination_data = {
        "type": "Snowflake",
        "config": {
            "user": "hazzadous",
            "password": "password",
            "account": "account",
            "database": "PostHog",
            "schema": "test",
            "warehouse": "COMPUTE_WH",
            "table_name": "events",
        },
    }

    batch_export_data = {
        "name": "my-production-snowflake-bucket-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    organization = await acreate_organization("test")
    team = await acreate_team(organization=organization)
    batch_export = await acreate_batch_export(
        team_id=team.pk,
        name=batch_export_data["name"],
        destination_data=batch_export_data["destination"],
        interval=batch_export_data["interval"],
    )

    # Create enough events to ensure we span more than 5MB, the smallest
    # multipart chunk size for multipart uploads to Snowflake.
    events: list[EventValues] = [
        {
            "_timestamp": "2023-04-20 14:30:00",
            "created_at": f"2023-04-20 14:30:00.{i:06d}",
            "distinct_id": str(uuid4()),
            "elements_chain": None,
            "event": "test",
            "inserted_at": f"2023-04-20 14:30:00.{i:06d}",
            "person_id": str(uuid4()),
            "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "person_properties": {},
            "team_id": team.pk,
            "timestamp": f"2023-04-20 14:30:00.{i:06d}",
            "uuid": str(uuid4()),
        }
        # NOTE: we have to do a lot here, otherwise we do not trigger a
        # multipart upload, and the minimum part chunk size is 5MB.
        for i in range(2)
    ]

    # Insert some data into the `sharded_events` table.
    await insert_events(
        client=ch_client,
        events=events,
    )

    other_team = await acreate_team(organization=organization)

    # Insert some events before the hour and after the hour, as well as some
    # events from another team to ensure that we only export the events from
    # the team that the batch export is for.
    await insert_events(
        client=ch_client,
        events=[
            {
                "_timestamp": "2023-04-20 13:30:00",
                "created_at": "2023-04-20 13:30:00",
                "distinct_id": str(uuid4()),
                "elements_chain": None,
                "event": "test",
                "inserted_at": "2023-04-20 13:30:00",
                "person_id": str(uuid4()),
                "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "person_properties": {},
                "team_id": team.pk,
                "timestamp": "2023-04-20 13:30:00",
                "uuid": str(uuid4()),
            },
            {
                "_timestamp": "2023-04-20 15:30:00",
                "created_at": "2023-04-20 15:30:00",
                "distinct_id": str(uuid4()),
                "elements_chain": None,
                "event": "test",
                "inserted_at": "2023-04-20 15:30:00",
                "person_id": str(uuid4()),
                "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "person_properties": {},
                "team_id": team.pk,
                "timestamp": "2023-04-20 15:30:00",
                "uuid": str(uuid4()),
            },
            {
                "_timestamp": "2023-04-20 14:30:00",
                "created_at": "2023-04-20 14:30:00",
                "distinct_id": str(uuid4()),
                "elements_chain": None,
                "event": "test",
                "inserted_at": "2023-04-20 14:30:00",
                "person_id": str(uuid4()),
                "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "person_properties": {},
                "team_id": other_team.pk,
                "timestamp": "2023-04-20 14:30:00",
                "uuid": str(uuid4()),
            },
        ],
    )

    workflow_id = str(uuid4())
    inputs = SnowflakeBatchExportInputs(
        team_id=team.pk,
        batch_export_id=str(batch_export.id),
        data_interval_end="2023-04-20 14:40:00.000000",
        **batch_export.destination.config,
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[SnowflakeBatchExportWorkflow],
            activities=[create_export_run, insert_into_snowflake_activity, update_export_run_status],
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
                expected_events = [
                    {
                        key: value
                        for key, value in event.items()
                        if key in ("uuid", "event", "timestamp", "properties", "person_id")
                    }
                    for event in events
                ]
                assert json_data[0] == expected_events[0]
                assert json_data == expected_events

        runs = await afetch_batch_export_runs(batch_export_id=batch_export.id)
        assert len(runs) == 1

        run = runs[0]
        assert run.status == "Completed"

    # Check that the workflow runs successfully for a period that has no
    # events.

    inputs = SnowflakeBatchExportInputs(
        team_id=team.pk,
        batch_export_id=str(batch_export.id),
        data_interval_end="2023-03-20 14:40:00.000000",
        **batch_export.destination.config,
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[SnowflakeBatchExportWorkflow],
            activities=[create_export_run, insert_into_snowflake_activity, update_export_run_status],
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

        runs = await afetch_batch_export_runs(batch_export_id=batch_export.id)
        assert len(runs) == 2

        run = runs[1]
        assert run.status == "Completed"


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_snowflake_export_workflow_raises_error_on_put_fail():
    destination_data = {
        "type": "Snowflake",
        "config": {
            "user": "hazzadous",
            "password": "password",
            "account": "account",
            "database": "PostHog",
            "schema": "test",
            "warehouse": "COMPUTE_WH",
            "table_name": "events",
        },
    }

    batch_export_data = {
        "name": "my-production-snowflake-bucket-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    organization = await acreate_organization("test")
    team = await acreate_team(organization=organization)
    batch_export = await acreate_batch_export(
        team_id=team.pk,
        name=batch_export_data["name"],
        destination_data=batch_export_data["destination"],
        interval=batch_export_data["interval"],
    )

    ch_client = ClickHouseClient(
        url=settings.CLICKHOUSE_HTTP_URL,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
    )

    events: list[EventValues] = [
        {
            "_timestamp": "2023-04-20 14:30:00",
            "created_at": "2023-04-20 14:30:00",
            "distinct_id": str(uuid4()),
            "elements_chain": None,
            "event": "test",
            "inserted_at": f"2023-04-20 14:30:00.{i:06d}",
            "person_id": str(uuid4()),
            "person_properties": None,
            "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team.pk,
            "timestamp": f"2023-04-20 14:30:00.{i:06d}",
            "uuid": str(uuid4()),
        }
        for i in range(2)
    ]

    await insert_events(
        client=ch_client,
        events=events,
    )

    inputs = SnowflakeBatchExportInputs(
        team_id=team.pk,
        batch_export_id=str(batch_export.id),
        data_interval_end="2023-04-20 14:40:00.000000",
        **batch_export.destination.config,
    )

    workflow_id = str(uuid4())

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[SnowflakeBatchExportWorkflow],
            activities=[create_export_run, insert_into_snowflake_activity, update_export_run_status],
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


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_snowflake_export_workflow_raises_error_on_copy_fail():
    destination_data = {
        "type": "Snowflake",
        "config": {
            "user": "hazzadous",
            "password": "password",
            "account": "account",
            "database": "PostHog",
            "schema": "test",
            "warehouse": "COMPUTE_WH",
            "table_name": "events",
        },
    }

    batch_export_data = {
        "name": "my-production-snowflake-bucket-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    organization = await acreate_organization("test")
    team = await acreate_team(organization=organization)
    batch_export = await acreate_batch_export(
        team_id=team.pk,
        name=batch_export_data["name"],
        destination_data=batch_export_data["destination"],
        interval=batch_export_data["interval"],
    )

    ch_client = ClickHouseClient(
        url=settings.CLICKHOUSE_HTTP_URL,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
    )

    events: list[EventValues] = [
        {
            "_timestamp": "2023-04-20 14:30:00",
            "created_at": "2023-04-20 14:30:00",
            "distinct_id": str(uuid4()),
            "elements_chain": None,
            "event": "test",
            "inserted_at": f"2023-04-20 14:30:00.{i:06d}",
            "person_id": str(uuid4()),
            "person_properties": None,
            "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team.pk,
            "timestamp": f"2023-04-20 14:30:00.{i:06d}",
            "uuid": str(uuid4()),
        }
        for i in range(2)
    ]

    await insert_events(
        client=ch_client,
        events=events,
    )

    inputs = SnowflakeBatchExportInputs(
        team_id=team.pk,
        batch_export_id=str(batch_export.id),
        data_interval_end="2023-04-20 14:40:00.000000",
        **batch_export.destination.config,
    )

    workflow_id = str(uuid4())

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[SnowflakeBatchExportWorkflow],
            activities=[create_export_run, insert_into_snowflake_activity, update_export_run_status],
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
