import re
import json
import uuid
import typing as t
import datetime as dt

import pytest
from unittest import mock
from unittest.mock import patch

from django.conf import settings

from posthog.batch_exports.service import BackfillDetails, BatchExportModel
from posthog.temporal.common.clickhouse import ClickHouseClient

from products.batch_exports.backend.temporal.pipeline.internal_stage import (
    BatchExportInsertIntoInternalStageInputs,
    get_s3_staging_folder,
    insert_into_internal_stage_activity,
)
from products.batch_exports.backend.tests.temporal.utils.s3 import (
    assert_files_in_s3,
    create_test_client,
    delete_all_from_s3,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]

TEST_DATA_INTERVAL_END = dt.datetime.now(tz=dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)


class MockClickHouseClient:
    """Helper class to mock ClickHouse client."""

    def __init__(self):
        self.mock_client = mock.AsyncMock(spec=ClickHouseClient)
        self.mock_client_cm = mock.AsyncMock()
        self.mock_client_cm.__aenter__.return_value = self.mock_client
        self.mock_client_cm.__aexit__.return_value = None

    def expect_select_from_table(self, table_name: str) -> None:
        """Assert that the executed query selects from the expected table.

        Args:
            table_name: The name of the table to check for in the FROM clause.

        The method handles different formatting of the FROM clause, including newlines
        and varying amounts of whitespace.
        """
        assert self.mock_client.execute_query.call_count == 1
        call_args = self.mock_client.execute_query.call_args
        query = call_args[0][0]  # First positional argument of the first call

        # Create a pattern that matches "FROM" followed by optional whitespace/newlines and then the table name
        pattern = rf"FROM\s+{re.escape(table_name)}"
        assert re.search(pattern, query, re.IGNORECASE), f"Query does not select FROM {table_name}"

    def expect_properties_in_log_comment(self, properties: dict[str, t.Any]) -> None:
        """Assert that the executed query has the expected properties in the log comment."""
        assert self.mock_client.execute_query.call_count == 1
        call_args = self.mock_client.execute_query.call_args
        # assert that log_comment is in the query
        query = call_args[0][0]
        assert "log_comment" in query, "log_comment is not in the query"
        # check that the log_comment is passed in as a query parameter
        query_parameters = call_args[1].get("query_parameters", {})
        log_comment = query_parameters.get("log_comment")
        assert log_comment is not None
        assert isinstance(log_comment, str)
        log_comment_dict = json.loads(log_comment)
        for key, value in properties.items():
            assert log_comment_dict[key] == value


@pytest.fixture
def mock_clickhouse_client():
    """Fixture to mock ClickHouse client."""
    mock_client = MockClickHouseClient()
    with patch(
        "products.batch_exports.backend.temporal.pipeline.internal_stage.get_client",
        return_value=mock_client.mock_client_cm,
    ):
        yield mock_client


@pytest.mark.parametrize("interval", ["day", "every 5 minutes"], indirect=True)
@pytest.mark.parametrize(
    "model",
    [
        BatchExportModel(name="events", schema=None),
    ],
)
@pytest.mark.parametrize("is_backfill", [False, True])
@pytest.mark.parametrize("backfill_within_last_6_days", [False, True])
@pytest.mark.parametrize("data_interval_end", [TEST_DATA_INTERVAL_END])
async def test_insert_into_stage_activity_executes_the_expected_query_for_events_model(
    mock_clickhouse_client,
    interval,
    activity_environment,
    data_interval_start,
    data_interval_end,
    ateam,
    model: BatchExportModel,
    is_backfill: bool,
    backfill_within_last_6_days: bool,
):
    """Test that the insert_into_internal_stage_activity executes the expected ClickHouse query when the model is an events model.

    The query used for the events model is quite complex, and depends on a number of factors:
    - If it's a backfill
    - How far in the past we're backfilling
    - If it's a 5 min batch export
    """

    if not is_backfill and backfill_within_last_6_days:
        pytest.skip("No need to test backfill within last 6 days for non-backfill")

    expected_table = "distributed_events_recent"
    if not is_backfill and interval == "every 5 minutes":
        expected_table = "events_recent"
    elif is_backfill and not backfill_within_last_6_days:
        expected_table = "events"

    if backfill_within_last_6_days:
        backfill_start_at = (data_interval_end - dt.timedelta(days=3)).isoformat()
    else:
        backfill_start_at = (data_interval_end - dt.timedelta(days=10)).isoformat()

    exclude_events = None
    include_events = None

    insert_inputs = BatchExportInsertIntoInternalStageInputs(
        team_id=ateam.pk,
        batch_export_id=str(uuid.uuid4()),
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        include_events=include_events,
        run_id=None,
        batch_export_schema=None,
        batch_export_model=model,
        backfill_details=BackfillDetails(
            backfill_id=None,
            start_at=backfill_start_at,
            end_at=data_interval_end,
            is_earliest_backfill=False,
        )
        if is_backfill
        else None,
        destination_default_fields=None,
    )

    await activity_environment.run(insert_into_internal_stage_activity, insert_inputs)
    mock_clickhouse_client.expect_select_from_table(expected_table)
    mock_clickhouse_client.expect_properties_in_log_comment(
        {
            "team_id": insert_inputs.team_id,
            "batch_export_id": insert_inputs.batch_export_id,
            "product": "batch_export",
        },
    )


@pytest.mark.parametrize("interval", ["day"], indirect=True)
@pytest.mark.parametrize(
    "model",
    [
        BatchExportModel(name="sessions", schema=None),
    ],
)
@pytest.mark.parametrize("data_interval_end", [TEST_DATA_INTERVAL_END])
async def test_insert_into_stage_activity_executes_the_expected_query_for_sessions_model(
    mock_clickhouse_client,
    interval,
    activity_environment,
    data_interval_start,
    data_interval_end,
    ateam,
    model: BatchExportModel,
):
    """Test that the insert_into_internal_stage_activity executes the expected ClickHouse query when the model is a sessions model."""

    expected_table = "raw_sessions"

    insert_inputs = BatchExportInsertIntoInternalStageInputs(
        team_id=ateam.pk,
        batch_export_id=str(uuid.uuid4()),
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=None,
        include_events=None,
        run_id=None,
        batch_export_schema=None,
        batch_export_model=model,
        backfill_details=None,
        destination_default_fields=None,
    )

    await activity_environment.run(insert_into_internal_stage_activity, insert_inputs)
    mock_clickhouse_client.expect_select_from_table(expected_table)
    mock_clickhouse_client.expect_properties_in_log_comment(
        {
            "team_id": insert_inputs.team_id,
            "batch_export_id": insert_inputs.batch_export_id,
            "product": "batch_export",
        }
    )


@pytest.fixture
async def minio_client():
    """Manage an S3 client to interact with a MinIO bucket."""
    async with create_test_client(
        "s3",
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
    ) as minio_client:
        yield minio_client

        await delete_all_from_s3(minio_client, settings.BATCH_EXPORT_INTERNAL_STAGING_BUCKET, key_prefix="")


@pytest.mark.parametrize("interval", ["day", "every 5 minutes"], indirect=True)
# single quotes in parameters have caused query formatting to break in the past
@pytest.mark.parametrize("exclude_events", [None, ["'"]])
@pytest.mark.parametrize(
    "model",
    [
        BatchExportModel(name="events", schema=None),
    ],
)
@pytest.mark.parametrize("data_interval_end", [TEST_DATA_INTERVAL_END])
async def test_insert_into_stage_activity_for_events_model(
    generate_test_data,
    interval,
    activity_environment,
    data_interval_start,
    minio_client,
    data_interval_end,
    ateam,
    model: BatchExportModel,
    exclude_events,
):
    """Test that the insert_into_internal_stage_activity produces expected files in S3."""

    include_events = None
    batch_export_id = str(uuid.uuid4())

    insert_inputs = BatchExportInsertIntoInternalStageInputs(
        team_id=ateam.pk,
        batch_export_id=batch_export_id,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        include_events=include_events,
        run_id=None,
        batch_export_schema=None,
        batch_export_model=model,
        backfill_details=None,
        destination_default_fields=None,
    )

    await activity_environment.run(insert_into_internal_stage_activity, insert_inputs)

    await assert_files_in_s3(
        minio_client,
        bucket_name=settings.BATCH_EXPORT_INTERNAL_STAGING_BUCKET,
        key_prefix=get_s3_staging_folder(
            batch_export_id,
            data_interval_start=data_interval_start.isoformat(),
            data_interval_end=data_interval_end.isoformat(),
        ),
        file_format="Arrow",
        compression=None,
        json_columns=None,
    )
