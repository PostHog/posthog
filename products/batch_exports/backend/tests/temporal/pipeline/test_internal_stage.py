import contextlib
import datetime as dt
import json
import re
import typing as t
import uuid
from collections.abc import Collection
from unittest import mock
from unittest.mock import patch

import pyarrow as pa
import pytest

from posthog.batch_exports.service import (
    BackfillDetails,
    BatchExportModel,
)
from posthog.temporal.common.clickhouse import ClickHouseClient
from products.batch_exports.backend.temporal.pipeline.internal_stage import (
    BatchExportInsertIntoInternalStageInputs,
    insert_into_internal_stage_activity,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]

TEST_DATA_INTERVAL_END = dt.datetime.now(tz=dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)


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
        run_id=str(uuid.uuid4()),
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

    class MockClickHouseClient:
        """Helper class to mock ClickHouse client."""

        def __init__(self):
            self.mock_client = mock.AsyncMock(spec=ClickHouseClient)
            self.mock_client_cm = mock.AsyncMock()
            self.mock_client_cm.__aenter__.return_value = self.mock_client
            self.mock_client_cm.__aexit__.return_value = None

            # Set up the mock to return our async iterator
            self.mock_client.astream_query_as_arrow.return_value = self._create_record_batch_iterator()

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

        @staticmethod
        def _create_test_record_batch() -> pa.RecordBatch:
            """Create a record batch with test data."""
            schema = pa.schema(
                [
                    ("team_id", pa.int64()),
                    ("timestamp", pa.timestamp("us")),
                    ("event", pa.string()),
                    ("distinct_id", pa.string()),
                    ("uuid", pa.string()),
                    ("_inserted_at", pa.timestamp("us")),
                    ("created_at", pa.timestamp("us")),
                    ("elements_chain", pa.string()),
                    ("person_id", pa.string()),
                    ("properties", pa.string()),  # JSON string
                    ("person_properties", pa.string()),  # JSON string
                    ("set", pa.string()),  # JSON string
                    ("set_once", pa.string()),  # JSON string
                ]
            )

            now = dt.datetime.now(dt.UTC)
            arrays: Collection[pa.Array[t.Any]] = [
                pa.array([1]),  # team_id
                pa.array([now]),  # timestamp
                pa.array(["test_event"]),  # event
                pa.array(["test_distinct_id"]),  # distinct_id
                pa.array([str(uuid.uuid4())]),  # uuid
                pa.array([now]),  # _inserted_at
                pa.array([now]),  # created_at
                pa.array(["div > button"]),  # elements_chain
                pa.array([str(uuid.uuid4())]),  # person_id
                pa.array([json.dumps({"prop1": "value1"})]),  # properties
                pa.array([json.dumps({"person_prop1": "value1"})]),  # person_properties
                pa.array([json.dumps({"set1": "value1"})]),  # set
                pa.array([json.dumps({"set_once1": "value1"})]),  # set_once
            ]
            return pa.RecordBatch.from_arrays(arrays, schema=schema)

        async def _create_record_batch_iterator(self):
            """Create an async iterator that yields a single record batch with test data."""
            yield self._create_test_record_batch()

    @contextlib.contextmanager
    def mock_clickhouse_client():
        """Context manager to mock ClickHouse client."""
        mock_client = MockClickHouseClient()
        with patch(
            "products.batch_exports.backend.temporal.pipeline.internal_stage.get_client",
            return_value=mock_client.mock_client_cm,
        ):
            yield mock_client

    with mock_clickhouse_client() as mock_client:
        await activity_environment.run(insert_into_internal_stage_activity, insert_inputs)
        mock_client.expect_select_from_table(expected_table)
