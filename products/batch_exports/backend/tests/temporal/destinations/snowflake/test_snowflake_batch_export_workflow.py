import asyncio
import dataclasses
import datetime as dt
import io
import os
import unittest.mock
import uuid
from uuid import uuid4

import paramiko
import pytest
from django.test import override_settings
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog import constants
from posthog.batch_exports.models import BatchExport, BatchExportRun
from posthog.batch_exports.service import (
    BackfillDetails,
    BatchExportModel,
    BatchExportSchema,
)
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse
from posthog.temporal.tests.utils.models import (
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
)
from products.batch_exports.backend.temporal.spmc import (
    RecordBatchTaskError,
)
from products.batch_exports.backend.tests.temporal.destinations.snowflake.utils import (
    FakeSnowflakeConnection,
    assert_clickhouse_records_in_snowflake,
)
from products.batch_exports.backend.tests.temporal.utils import (
    FlakyClickHouseClient,
    mocked_start_batch_export_run,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


TEST_TIME = dt.datetime.now(dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)

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


async def _run_workflow(
    team_id: int,
    batch_export_id: int,
    interval: str,
    snowflake_batch_export: BatchExport,
    data_interval_end: dt.datetime = TEST_TIME,
) -> BatchExportRun:
    workflow_id = str(uuid4())
    inputs = SnowflakeBatchExportInputs(
        team_id=team_id,
        batch_export_id=str(batch_export_id),
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
            await activity_environment.client.execute_workflow(
                SnowflakeBatchExportWorkflow.run,
                inputs,
                id=workflow_id,
                execution_timeout=dt.timedelta(seconds=10),
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )

    runs = await afetch_batch_export_runs(batch_export_id=snowflake_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    return run


class TestSnowflakeExportWorkflowMockedConnection:
    @pytest.mark.parametrize("interval", ["hour"], indirect=True)
    async def test_snowflake_export_workflow_exports_events(
        self, ateam, clickhouse_client, database, schema, snowflake_batch_export, interval, table_name
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
        with (
            unittest.mock.patch(
                "products.batch_exports.backend.temporal.destinations.snowflake_batch_export.snowflake.connector.connect",
            ) as mock,
            override_settings(BATCH_EXPORT_SNOWFLAKE_UPLOAD_CHUNK_SIZE_BYTES=1),
        ):
            fake_conn = FakeSnowflakeConnection()
            mock.return_value = fake_conn
            run = await _run_workflow(
                team_id=ateam.pk,
                batch_export_id=snowflake_batch_export.id,
                data_interval_end=data_interval_end,
                interval=interval,
                snowflake_batch_export=snowflake_batch_export,
            )
            assert run.status == "Completed"
            assert run.records_completed == 10

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

    @pytest.mark.parametrize("interval", ["hour"], indirect=True)
    async def test_snowflake_export_workflow_without_events(
        self, ateam, snowflake_batch_export, interval, truncate_events
    ):
        data_interval_end = dt.datetime.now(tz=dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)

        with (
            unittest.mock.patch(
                "products.batch_exports.backend.temporal.destinations.snowflake_batch_export.snowflake.connector.connect",
            ) as mock,
            override_settings(BATCH_EXPORT_SNOWFLAKE_UPLOAD_CHUNK_SIZE_BYTES=1),
        ):
            fake_conn = FakeSnowflakeConnection()
            mock.return_value = fake_conn
            run = await _run_workflow(
                team_id=ateam.pk,
                batch_export_id=snowflake_batch_export.id,
                data_interval_end=data_interval_end,
                interval=interval,
                snowflake_batch_export=snowflake_batch_export,
            )
            assert run.status == "Completed"
            assert run.records_completed == 0


class TestSnowflakeExportWorkflowErrorHandling:
    async def test_snowflake_export_workflow_raises_error_on_put_fail(
        self, clickhouse_client, ateam, snowflake_batch_export, interval
    ):
        data_interval_end = TEST_TIME
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

        class FakeSnowflakeConnectionFailOnPut(FakeSnowflakeConnection):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, failure_mode="put", **kwargs)

        with unittest.mock.patch(
            "products.batch_exports.backend.temporal.destinations.snowflake_batch_export.snowflake.connector.connect",
            side_effect=FakeSnowflakeConnectionFailOnPut,
        ):
            with pytest.raises(WorkflowFailureError) as exc_info:
                run = await _run_workflow(
                    team_id=ateam.pk,
                    batch_export_id=snowflake_batch_export.id,
                    data_interval_end=data_interval_end,
                    interval=interval,
                    snowflake_batch_export=snowflake_batch_export,
                )
                assert run.status == "FailedRetryable"
                assert run.latest_error == "SnowflakeFileNotUploadedError"

            err = exc_info.value
            assert hasattr(err, "__cause__"), "Workflow failure missing cause"
            assert isinstance(err.__cause__, ActivityError)
            assert isinstance(err.__cause__.__cause__, ApplicationError)
            assert err.__cause__.__cause__.type == "SnowflakeFileNotUploadedError"

    async def test_snowflake_export_workflow_raises_error_on_copy_fail(
        self, clickhouse_client, ateam, snowflake_batch_export, interval
    ):
        data_interval_end = dt.datetime.now(tz=dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
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

        class FakeSnowflakeConnectionFailOnCopy(FakeSnowflakeConnection):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, failure_mode="copy", **kwargs)

        with unittest.mock.patch(
            "products.batch_exports.backend.temporal.destinations.snowflake_batch_export.snowflake.connector.connect",
            side_effect=FakeSnowflakeConnectionFailOnCopy,
        ):
            with pytest.raises(WorkflowFailureError) as exc_info:
                run = await _run_workflow(
                    team_id=ateam.pk,
                    batch_export_id=snowflake_batch_export.id,
                    data_interval_end=data_interval_end,
                    interval=interval,
                    snowflake_batch_export=snowflake_batch_export,
                )
                assert run.status == "FailedRetryable"
                assert run.latest_error == "SnowflakeFileNotLoadedError"

            err = exc_info.value
            assert hasattr(err, "__cause__"), "Workflow failure missing cause"
            assert isinstance(err.__cause__, ActivityError)
            assert isinstance(err.__cause__.__cause__, ApplicationError)
            assert err.__cause__.__cause__.type == "SnowflakeFileNotLoadedError"

    async def test_snowflake_export_workflow_handles_unexpected_insert_activity_errors(
        self, ateam, snowflake_batch_export, interval
    ):
        """Test that Snowflake Export Workflow can gracefully handle unexpected errors when inserting Snowflake data.

        This means we do the right updates to the BatchExportRun model and ensure the workflow fails (since we
        treat this as an unexpected internal error).

        To simulate an unexpected error, we mock the `Producer.start` activity.
        """

        with unittest.mock.patch(
            "products.batch_exports.backend.temporal.destinations.snowflake_batch_export.Producer.start",
            side_effect=ValueError("A useful error message"),
        ):
            with pytest.raises(WorkflowFailureError):
                run = await _run_workflow(
                    team_id=ateam.pk,
                    batch_export_id=snowflake_batch_export.id,
                    interval=interval,
                    snowflake_batch_export=snowflake_batch_export,
                )
                assert run.status == "FailedRetryable"
                assert run.latest_error == "ValueError: A useful error message"
                assert run.records_completed is None

    async def test_snowflake_export_workflow_handles_insert_activity_non_retryable_errors(
        self, ateam, snowflake_batch_export, interval
    ):
        """Test that Snowflake Export Workflow can gracefully handle non-retryable errors when inserting Snowflake data.

        In this case, we expect the workflow to succeed, but the batch export run to be marked as failed.

        To simulate a user error, we mock the `Producer.start` activity.
        """

        class ForbiddenError(Exception):
            pass

        with unittest.mock.patch(
            "products.batch_exports.backend.temporal.destinations.snowflake_batch_export.Producer.start",
            side_effect=ForbiddenError("A useful error message"),
        ):
            run = await _run_workflow(
                team_id=ateam.pk,
                batch_export_id=snowflake_batch_export.id,
                interval=interval,
                snowflake_batch_export=snowflake_batch_export,
            )
        assert run.status == "Failed"
        assert run.latest_error == "ForbiddenError: A useful error message"
        assert run.records_completed is None

    async def test_snowflake_export_workflow_handles_cancellation_mocked(self, ateam, snowflake_batch_export):
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


@SKIP_IF_MISSING_REQUIRED_ENV_VARS
class TestInsertIntoSnowflakeActivity:
    async def _run_activity(
        self,
        activity_environment,
        snowflake_cursor,
        clickhouse_client,
        snowflake_config,
        team,
        data_interval_start,
        data_interval_end,
        table_name: str,
        batch_export_model: BatchExportModel | None = None,
        batch_export_schema: BatchExportSchema | None = None,
        exclude_events=None,
        sort_key: str = "event",
        expected_fields=None,
        expect_duplicates: bool = False,
        primary_key=None,
    ):
        """Helper function to run insert_into_snowflake_activity and assert records in Snowflake"""
        insert_inputs = SnowflakeInsertInputs(
            team_id=team.pk,
            table_name=table_name,
            data_interval_start=data_interval_start.isoformat(),
            data_interval_end=data_interval_end.isoformat(),
            exclude_events=exclude_events,
            batch_export_schema=batch_export_schema,
            batch_export_model=batch_export_model,
            **snowflake_config,
        )

        await activity_environment.run(insert_into_snowflake_activity, insert_inputs)

        await assert_clickhouse_records_in_snowflake(
            snowflake_cursor=snowflake_cursor,
            clickhouse_client=clickhouse_client,
            table_name=table_name,
            team_id=team.pk,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            exclude_events=exclude_events,
            batch_export_model=batch_export_model or batch_export_schema,
            sort_key=sort_key,
            expected_fields=expected_fields,
            expect_duplicates=expect_duplicates,
            primary_key=primary_key,
        )

    @pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
    @pytest.mark.parametrize("model", TEST_MODELS)
    async def test_insert_into_snowflake_activity_inserts_data_into_snowflake_table(
        self,
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

        sort_key = "event"
        if batch_export_model is not None:
            if batch_export_model.name == "persons":
                sort_key = "person_id"
            elif batch_export_model.name == "sessions":
                sort_key = "session_id"

        await self._run_activity(
            activity_environment=activity_environment,
            snowflake_cursor=snowflake_cursor,
            clickhouse_client=clickhouse_client,
            snowflake_config=snowflake_config,
            team=ateam,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            table_name=table_name,
            batch_export_model=batch_export_model,
            batch_export_schema=batch_export_schema,
            exclude_events=exclude_events,
            sort_key=sort_key,
        )

    async def test_insert_into_snowflake_activity_merges_persons_data_in_follow_up_runs(
        self,
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

        await self._run_activity(
            activity_environment=activity_environment,
            snowflake_cursor=snowflake_cursor,
            clickhouse_client=clickhouse_client,
            snowflake_config=snowflake_config,
            team=ateam,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            table_name=table_name,
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

        await self._run_activity(
            activity_environment=activity_environment,
            snowflake_cursor=snowflake_cursor,
            clickhouse_client=clickhouse_client,
            snowflake_config=snowflake_config,
            team=ateam,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            table_name=table_name,
            batch_export_model=model,
            sort_key="person_id",
        )

    async def test_insert_into_snowflake_activity_merges_sessions_data_in_follow_up_runs(
        self,
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

        await self._run_activity(
            activity_environment=activity_environment,
            snowflake_cursor=snowflake_cursor,
            clickhouse_client=clickhouse_client,
            snowflake_config=snowflake_config,
            team=ateam,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            table_name=table_name,
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

        await self._run_activity(
            activity_environment=activity_environment,
            snowflake_cursor=snowflake_cursor,
            clickhouse_client=clickhouse_client,
            snowflake_config=snowflake_config,
            team=ateam,
            data_interval_start=new_data_interval_start,
            data_interval_end=new_data_interval_end,
            table_name=table_name,
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

    async def test_insert_into_snowflake_activity_removes_internal_stage_files(
        self,
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

        await self._run_activity(
            activity_environment=activity_environment,
            snowflake_cursor=snowflake_cursor,
            clickhouse_client=clickhouse_client,
            snowflake_config=snowflake_config,
            team=ateam,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            table_name=table_name,
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

        await self._run_activity(
            activity_environment=activity_environment,
            snowflake_cursor=snowflake_cursor,
            clickhouse_client=clickhouse_client,
            snowflake_config=snowflake_config,
            team=ateam,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            table_name=table_name,
            batch_export_model=model,
            sort_key="event",
        )

        snowflake_cursor.execute(list_query)
        rows = snowflake_cursor.fetchall()
        assert len(rows) == 0

    async def test_insert_into_snowflake_activity_heartbeats(
        self,
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

    async def test_insert_into_snowflake_activity_handles_person_schema_changes(
        self,
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

        await self._run_activity(
            activity_environment=activity_environment,
            snowflake_cursor=snowflake_cursor,
            clickhouse_client=clickhouse_client,
            snowflake_config=snowflake_config,
            team=ateam,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            table_name=table_name,
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

        # This time we don't expect there to be a created_at column
        expected_fields = [field for field in EXPECTED_PERSONS_BATCH_EXPORT_FIELDS if field != "created_at"]
        await self._run_activity(
            activity_environment=activity_environment,
            snowflake_cursor=snowflake_cursor,
            clickhouse_client=clickhouse_client,
            snowflake_config=snowflake_config,
            team=ateam,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            table_name=table_name,
            batch_export_model=model,
            sort_key="person_id",
            expected_fields=expected_fields,
        )

    @pytest.mark.parametrize(
        "model", [BatchExportModel(name="events", schema=None), BatchExportModel(name="persons", schema=None)]
    )
    async def test_insert_into_snowflake_activity_completes_range_when_there_is_a_failure(
        self,
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


@SKIP_IF_MISSING_REQUIRED_ENV_VARS
class TestSnowflakeExportWorkflow:
    @pytest.mark.parametrize("interval", ["hour", "day"], indirect=True)
    @pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
    @pytest.mark.parametrize("model", TEST_MODELS)
    async def test_snowflake_export_workflow(
        self,
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
        """Test Snowflake Export Workflow end-to-end.

        The workflow should update the batch export run status to completed and produce the expected
        records to the provided Snowflake instance.
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

    @pytest.mark.parametrize("interval", ["hour", "day"], indirect=True)
    @pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
    @pytest.mark.parametrize("model", TEST_MODELS)
    async def test_snowflake_export_workflow_with_many_files(
        self,
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
        self,
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
            data_interval_end - person["_timestamp"].replace(tzinfo=dt.UTC) > dt.timedelta(hours=12)
            for person in persons
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

    async def test_snowflake_export_workflow_handles_cancellation(
        self, clickhouse_client, ateam, snowflake_batch_export, interval, snowflake_cursor
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


class TestSnowflakeKeyPairAuth:
    def test_load_private_key_raises_error_if_key_is_invalid(self):
        with pytest.raises(InvalidPrivateKeyError):
            load_private_key("invalid_key", None)

    def test_load_private_key_raises_error_if_incorrect_passphrase(self):
        """Test we raise the right error when passing an incorrect passphrase."""
        key = paramiko.RSAKey.generate(2048)
        buffer = io.StringIO()
        key.write_private_key(buffer, password="a-passphrase")
        _ = buffer.seek(0)

        with pytest.raises(InvalidPrivateKeyError) as exc_info:
            _ = load_private_key(buffer.read(), "another-passphrase")

        assert "incorrect passphrase" in str(exc_info.value)

    def test_load_private_key_raises_error_if_passphrase_not_empty(self):
        """Test we raise the right error when passing a passphrase to a key without one."""
        key = paramiko.RSAKey.generate(2048)
        buffer = io.StringIO()
        key.write_private_key(buffer)
        _ = buffer.seek(0)

        with pytest.raises(InvalidPrivateKeyError) as exc_info:
            _ = load_private_key(buffer.read(), "a-passphrase")

        assert "passphrase was given but private key is not encrypted" in str(exc_info.value)

    def test_load_private_key_raises_error_if_passphrase_missing(self):
        """Test we raise the right error when missing a passphrase to an encrypted key."""
        key = paramiko.RSAKey.generate(2048)
        buffer = io.StringIO()
        key.write_private_key(buffer, password="a-passphrase")
        _ = buffer.seek(0)

        with pytest.raises(InvalidPrivateKeyError) as exc_info:
            _ = load_private_key(buffer.read(), None)

        assert "passphrase was not given but private key is encrypted" in str(exc_info.value)

    def test_load_private_key_passes_with_empty_passphrase_and_no_encryption(self):
        """Test we succeed in loading a passphrase without encryption and an empty passphrase."""
        key = paramiko.RSAKey.generate(2048)
        buffer = io.StringIO()
        key.write_private_key(buffer, password=None)
        _ = buffer.seek(0)

        loaded = load_private_key(buffer.read(), "")

        assert loaded

    @pytest.mark.parametrize("passphrase", ["a-passphrase", None, ""])
    def test_load_private_key(self, passphrase: str | None):
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
