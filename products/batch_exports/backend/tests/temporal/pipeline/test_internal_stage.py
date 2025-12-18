import re
import json
import uuid
import typing as t
import asyncio
import datetime as dt
from collections.abc import AsyncGenerator

import pytest
from unittest import mock
from unittest.mock import patch

from django.conf import settings
from django.test.utils import override_settings

import pyarrow as pa
import pytest_asyncio
from temporalio.testing import ActivityEnvironment

from posthog.batch_exports.service import BackfillDetails, BatchExportModel
from posthog.temporal.common.clickhouse import ClickHouseClient

from products.batch_exports.backend.temporal.pipeline.internal_stage import (
    BatchExportInsertIntoInternalStageInputs,
    insert_into_internal_stage_activity,
)
from products.batch_exports.backend.temporal.pipeline.producer import Producer
from products.batch_exports.backend.temporal.spmc import RecordBatchQueue, wait_for_schema_or_producer
from products.batch_exports.backend.tests.temporal.utils.persons import (
    generate_test_person_distinct_id2_in_clickhouse,
    generate_test_persons_in_clickhouse,
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


@pytest_asyncio.fixture
async def minio_client():
    """Manage an S3 client to interact with a MinIO bucket."""
    async with create_test_client(
        "s3",
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
    ) as minio_client:
        yield minio_client

        await delete_all_from_s3(minio_client, settings.BATCH_EXPORT_INTERNAL_STAGING_BUCKET, key_prefix="")


async def _generate_record_batches_from_internal_stage(
    batch_export_id: str, data_interval_start: dt.datetime, data_interval_end: dt.datetime, stage_folder: str
) -> AsyncGenerator[pa.RecordBatch, None]:
    """Generate record batches from the internal stage."""
    queue = RecordBatchQueue()
    producer = Producer()
    producer_task = await producer.start(
        queue=queue,
        batch_export_id=batch_export_id,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        stage_folder=stage_folder,
    )
    await wait_for_schema_or_producer(queue, producer_task)

    while True:
        try:
            record_batch = queue.get_nowait()
            yield record_batch
        except asyncio.QueueEmpty:
            if producer_task.done():
                break
            else:
                await asyncio.sleep(0.1)
                continue


async def _run_activity(
    activity_environment: ActivityEnvironment,
    minio_client,
    team_id,
    data_interval_start: dt.datetime,
    data_interval_end: dt.datetime,
    exclude_events: list[str] | None = None,
    model: BatchExportModel | None = None,
) -> list[dict]:
    """Get rows from the internal stage."""

    batch_export_id = str(uuid.uuid4())
    insert_inputs = BatchExportInsertIntoInternalStageInputs(
        team_id=team_id,
        batch_export_id=batch_export_id,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        include_events=None,
        run_id=None,
        batch_export_schema=None,
        batch_export_model=model,
        backfill_details=None,
        destination_default_fields=None,
    )

    stage_folder = await activity_environment.run(insert_into_internal_stage_activity, insert_inputs)
    await assert_files_in_s3(
        minio_client,
        bucket_name=settings.BATCH_EXPORT_INTERNAL_STAGING_BUCKET,
        key_prefix=stage_folder,
        file_format="Arrow",
        compression=None,
        json_columns=None,
    )
    exported_rows = []
    async for record_batch in _generate_record_batches_from_internal_stage(
        batch_export_id, data_interval_start, data_interval_end, stage_folder
    ):
        exported_rows.extend(record_batch.to_pylist())
    return exported_rows


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
    """Test that the insert_into_internal_stage_activity produces expected data in the internal stage.

    For now we just check that the number of records exported is correct, not the content of the records.
    """

    records_exported = await _run_activity(
        activity_environment=activity_environment,
        minio_client=minio_client,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        exclude_events=exclude_events,
        model=model,
    )

    events_to_export_created = generate_test_data[0]

    assert len(records_exported) == len(events_to_export_created)


class PersonToExport(t.TypedDict):
    team_id: int
    person_id: str
    distinct_id: str
    person_version: int
    person_distinct_id_version: int
    properties: dict | None
    _timestamp: dt.datetime


async def _generate_persons_to_export(
    clickhouse_client: ClickHouseClient,
    team_id: int,
    data_interval_start: dt.datetime,
    data_interval_end: dt.datetime,
    test_person_properties: dict,
    count: int = 3,
    count_other_team: int = 3,
    count_distinct_ids_per_person: int = 1,
) -> list[PersonToExport]:
    persons, _ = await generate_test_persons_in_clickhouse(
        client=clickhouse_client,
        team_id=team_id,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=count,
        count_other_team=count_other_team,
        properties=test_person_properties,
    )

    persons_to_export_created = []
    for person in persons:
        for i in range(count_distinct_ids_per_person):
            person_distinct_id, _ = await generate_test_person_distinct_id2_in_clickhouse(
                client=clickhouse_client,
                team_id=team_id,
                person_id=uuid.UUID(person["id"]),
                distinct_id=f"distinct-id-{uuid.UUID(person['id'])}-{i}",
                timestamp=dt.datetime.fromisoformat(person["_timestamp"]),
            )
            person_to_export = PersonToExport(
                team_id=person["team_id"],
                person_id=person["id"],
                distinct_id=person_distinct_id["distinct_id"],
                person_version=person["version"],
                person_distinct_id_version=person_distinct_id["version"],
                properties=person["properties"],
                _timestamp=dt.datetime.fromisoformat(person["_timestamp"]),
            )
            persons_to_export_created.append(person_to_export)
    return persons_to_export_created


async def _generate_new_version_of_person(
    person: PersonToExport,
    clickhouse_client: ClickHouseClient,
    start_time: dt.datetime,
    end_time: dt.datetime,
):
    new_persons, _ = await generate_test_persons_in_clickhouse(
        client=clickhouse_client,
        team_id=person["team_id"],
        start_time=start_time,
        end_time=end_time,
        count=1,
        count_other_team=1,
        person_id=uuid.UUID(person["person_id"]),
        # generate a new version
        version=person["person_version"] + 1,
        properties=person["properties"],
    )
    return new_persons[0]


async def _generate_new_distinct_id_for_person(
    person: PersonToExport, clickhouse_client: ClickHouseClient, timestamp: dt.datetime
):
    new_distinct_id, _ = await generate_test_person_distinct_id2_in_clickhouse(
        client=clickhouse_client,
        team_id=person["team_id"],
        person_id=uuid.UUID(person["person_id"]),
        # generate a new distinct_id
        distinct_id=f"distinct-id-{uuid.uuid4()}",
        timestamp=timestamp,
    )
    return new_distinct_id


def assert_exported_rows_match_persons_to_export(exported_rows: list[dict], persons_to_export: list[PersonToExport]):
    assert len(exported_rows) == len(persons_to_export)

    # sort both lists by person_id and distinct_id for stable matching
    def export_key(row):
        return (row["person_id"], row["distinct_id"])

    exported_rows_formatted = sorted(
        [
            {
                "team_id": row["team_id"],
                "person_id": row["person_id"],
                "distinct_id": row["distinct_id"],
                "person_version": row["person_version"],
                "person_distinct_id_version": row["person_distinct_id_version"],
                "properties": json.loads(row["properties"]),
                "_timestamp": dt.datetime.fromtimestamp(row["_inserted_at"]),
            }
            for row in exported_rows
        ],
        key=export_key,
    )
    expected_rows = sorted(persons_to_export, key=export_key)
    assert exported_rows_formatted == expected_rows


@pytest.mark.parametrize("interval", ["day"], indirect=True)
@pytest.mark.parametrize("model", [BatchExportModel(name="persons", schema=None)])
@pytest.mark.parametrize("data_interval_end", [TEST_DATA_INTERVAL_END])
@pytest.mark.parametrize("limited_export", [False, True])
async def test_insert_into_stage_activity_for_persons_model(
    interval,
    activity_environment,
    data_interval_start,
    minio_client,
    data_interval_end,
    ateam,
    test_person_properties,
    clickhouse_client,
    model: BatchExportModel,
    limited_export: bool,
):
    """Test that the insert_into_internal_stage_activity produces expected data in the internal stage for the persons
    model.

    We perform a thorough test to ensure we're exporting the exact persons and distinct_ids we expect.

    We also test the 'limited export' mode, where we only export distinct_ids that have been created or updated in the
    data interval. (For context, we have certain cases where some customers have a large number of distinct_ids associated with a
    person, and we want to ensure that we're not exporting too many records.)
    """

    # first generate 3 persons with timestamps inside of the data interval
    # each of these persons will have 1 distinct_id associated with them
    persons_to_export_created = await _generate_persons_to_export(
        clickhouse_client=clickhouse_client,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        test_person_properties=test_person_properties,
    )

    records_exported = await _run_activity(
        activity_environment=activity_environment,
        minio_client=minio_client,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        model=model,
    )

    assert_exported_rows_match_persons_to_export(records_exported, persons_to_export_created)

    # now we generate some more data:
    # 1. we update the version of one person:
    #   - this should result in a single record being exported for the person, distinct_id pair
    #   - that is, unless we're in limited export mode, in which case we shouldn't expect any records to be exported, as
    #       this distinct_id is not new
    # 2. we create a new distinct id for the second person:
    #   - this should result in a single record being exported for the person, distinct_id pair
    #   - note that the existing distinct_id shouldn't be exported as well, since it's associated with the person
    # 3. we create a new person with 2 new distinct_ids associated with it:
    #   - this should result in 2 new records being exported for the person, distinct_id pairs
    next_data_interval_start = data_interval_end
    next_data_interval_end = data_interval_end + dt.timedelta(days=1)

    person_1: PersonToExport = persons_to_export_created[0]
    person_1_v2 = await _generate_new_version_of_person(
        person=person_1,
        clickhouse_client=clickhouse_client,
        start_time=next_data_interval_start,
        end_time=next_data_interval_end,
    )

    person_2: PersonToExport = persons_to_export_created[1]
    person_2_new_distinct_id = await _generate_new_distinct_id_for_person(
        person=person_2,
        clickhouse_client=clickhouse_client,
        timestamp=next_data_interval_start + dt.timedelta(seconds=1),
    )

    new_persons_to_export = []
    if not limited_export:
        new_persons_to_export.append(
            # since we have a new version of person_1 we should expect to export any distinct_ids associated with it
            # unless we're in limited export mode
            PersonToExport(
                team_id=person_1["team_id"],
                person_id=person_1["person_id"],
                person_version=person_1_v2["version"],
                distinct_id=person_1["distinct_id"],
                person_distinct_id_version=person_1["person_distinct_id_version"],
                properties=person_1_v2["properties"],
                _timestamp=dt.datetime.fromisoformat(person_1_v2["_timestamp"]),
            )
        )
    new_persons_to_export.append(
        # since we have a new distinct_id for person_2 we should expect to export it, but not the existing distinct_id
        PersonToExport(
            team_id=person_2["team_id"],
            person_id=person_2["person_id"],
            person_version=person_2["person_version"],
            distinct_id=person_2_new_distinct_id["distinct_id"],
            person_distinct_id_version=person_2_new_distinct_id["version"],
            properties=person_2["properties"],
            _timestamp=dt.datetime.fromisoformat(person_2_new_distinct_id["_timestamp"]),
        )
    )
    # person 3 should not be exported, since it's not in the data interval
    # create a new person with 2 new distinct_ids associated with it
    new_persons_to_export.extend(
        await _generate_persons_to_export(
            clickhouse_client=clickhouse_client,
            team_id=ateam.pk,
            data_interval_start=next_data_interval_start,
            data_interval_end=next_data_interval_end,
            test_person_properties=test_person_properties,
            count=1,
            count_other_team=1,
            count_distinct_ids_per_person=2,
        )
    )
    if not limited_export:
        # we should expect to export 4 records:
        # 1. the new version of person_1
        # 2. the new distinct_id for person_2
        # 3 & 4. the new person with 2 new distinct_ids
        assert len(new_persons_to_export) == 4
    else:
        # we should expect to export 3 records:
        # 1. the new distinct_id for person_2
        # 2 & 3. the new person with 2 new distinct_ids
        assert len(new_persons_to_export) == 3

    # update the interval and re-run the activity
    with override_settings(BATCH_EXPORTS_PERSONS_LIMITED_EXPORT_TEAM_IDS=[str(ateam.pk)] if limited_export else []):
        records_exported = await _run_activity(
            activity_environment=activity_environment,
            minio_client=minio_client,
            team_id=ateam.pk,
            data_interval_start=next_data_interval_start,
            data_interval_end=next_data_interval_end,
            model=model,
        )
    assert_exported_rows_match_persons_to_export(records_exported, new_persons_to_export)
