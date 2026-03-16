import uuid
import typing as t
import datetime as dt

import pytest
from unittest.mock import patch

from temporalio.testing import ActivityEnvironment

from posthog.batch_exports.models import BatchExport, BatchExportDestination
from posthog.models.utils import uuid7
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse, insert_sessions_in_clickhouse

from products.batch_exports.backend.temporal.backfill_batch_export import GetBackfillInfoInputs, get_backfill_info
from products.batch_exports.backend.tests.temporal.utils.clickhouse import (
    truncate_events,
    truncate_persons,
    truncate_sessions,
)
from products.batch_exports.backend.tests.temporal.utils.mock_clickhouse import MockClickHouseClient
from products.batch_exports.backend.tests.temporal.utils.persons import (
    generate_test_person_distinct_id2,
    generate_test_persons_in_clickhouse,
    insert_person_distinct_id2_values_in_clickhouse,
    insert_person_values_in_clickhouse,
)


@pytest.fixture
def activity_environment():
    return ActivityEnvironment()


@pytest.fixture
def run_get_backfill_info(activity_environment):
    async def _run(batch_export, start_at=None, end_at=None):
        inputs = GetBackfillInfoInputs(
            team_id=batch_export.team_id,
            batch_export_id=str(batch_export.id),
            start_at=start_at.isoformat() if start_at else None,
            end_at=end_at.isoformat() if end_at else None,
        )
        return await activity_environment.run(get_backfill_info, inputs)

    return _run


@pytest.fixture
def mock_clickhouse_client():
    mock_client = MockClickHouseClient(
        read_query_as_jsonl_responses=[[{"min_timestamp": "1970-01-01 00:00:00", "record_count": "0"}]],
    )
    with (
        patch(
            "products.batch_exports.backend.temporal.backfill_batch_export.get_client",
            return_value=mock_client.mock_client_cm,
        ),
        patch(
            "products.batch_exports.backend.temporal.record_batch_model.get_client",
            return_value=mock_client.mock_client_cm,
        ),
    ):
        yield mock_client


class TestGetBackfillInfoForEvents:
    @pytest.fixture(autouse=True)
    async def truncate_events_table(self, clickhouse_client):
        await truncate_events(clickhouse_client)

    @pytest.fixture
    def create_batch_export(self, ateam):
        async def _create(
            interval: str = "hour",
            interval_offset: int | None = None,
            timezone: str = "UTC",
            include_events: list[str] | None = None,
            exclude_events: list[str] | None = None,
        ) -> BatchExport:
            config: dict[str, t.Any] = {
                "bucket_name": "test",
                "region": "us-east-1",
                "prefix": "/",
                "aws_access_key_id": "key",
                "aws_secret_access_key": "secret",
            }
            if include_events:
                config["include_events"] = include_events
            if exclude_events:
                config["exclude_events"] = exclude_events
            destination = await BatchExportDestination.objects.acreate(type="S3", config=config)
            return await BatchExport.objects.acreate(
                team_id=ateam.pk,
                name="Test Batch Export",
                destination=destination,
                interval=interval,
                interval_offset=interval_offset,
                timezone=timezone,
            )

        return _create

    async def test_returns_earliest_start_and_count_when_data_exists(
        self, ateam, generate_events, create_batch_export, run_get_backfill_info
    ):
        event_time = dt.datetime(2021, 1, 15, 10, 30, 0, tzinfo=dt.UTC)
        await generate_events(start_time=event_time, count=25, count_other_team=10)

        batch_export = await create_batch_export()
        result = await run_get_backfill_info(batch_export, start_at=dt.datetime(2000, 1, 1, tzinfo=dt.UTC))

        assert result.adjusted_start_at == dt.datetime(2021, 1, 15, 10, 0, 0, tzinfo=dt.UTC).isoformat()
        assert result.total_records_count == 25

    async def test_returns_count_with_no_adjusted_start_when_start_at_is_none(
        self, ateam, generate_events, create_batch_export, run_get_backfill_info
    ):
        event_time = dt.datetime(2021, 1, 15, 10, 30, 0, tzinfo=dt.UTC)
        await generate_events(start_time=event_time, count=25, count_other_team=10)

        batch_export = await create_batch_export()
        result = await run_get_backfill_info(batch_export)

        assert result.adjusted_start_at is None
        assert result.total_records_count == 25

    async def test_returns_zero_when_no_data_exists(self, ateam, create_batch_export, run_get_backfill_info):
        batch_export = await create_batch_export()
        result = await run_get_backfill_info(batch_export)

        assert result.total_records_count == 0

    async def test_counts_only_events_after_start_at(
        self, ateam, generate_events, create_batch_export, run_get_backfill_info
    ):
        early_time = dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC)
        late_time = dt.datetime(2021, 1, 20, 0, 0, 0, tzinfo=dt.UTC)

        await generate_events(start_time=early_time, count=10, count_other_team=10)
        await generate_events(start_time=late_time, count=15, count_other_team=10)

        batch_export = await create_batch_export()
        result = await run_get_backfill_info(
            batch_export,
            start_at=dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC),
        )

        assert result.adjusted_start_at == dt.datetime(2021, 1, 20, 0, 0, 0, tzinfo=dt.UTC).isoformat()
        assert result.total_records_count == 15

    async def test_counts_only_events_before_end_at(
        self, ateam, generate_events, create_batch_export, run_get_backfill_info
    ):
        early_time = dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC)
        late_time = dt.datetime(2021, 1, 20, 0, 0, 0, tzinfo=dt.UTC)

        await generate_events(start_time=early_time, count=10, count_other_team=10)
        await generate_events(start_time=late_time, count=15, count_other_team=10)

        batch_export = await create_batch_export()
        result = await run_get_backfill_info(
            batch_export,
            start_at=dt.datetime(2000, 1, 1, tzinfo=dt.UTC),
            end_at=dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC),
        )

        assert result.adjusted_start_at == dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC).isoformat()
        assert result.total_records_count == 10

    async def test_counts_only_events_in_range(
        self, ateam, generate_events, create_batch_export, run_get_backfill_info
    ):
        times = [
            dt.datetime(2021, 1, 5, 0, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2021, 1, 25, 0, 0, 0, tzinfo=dt.UTC),
        ]
        counts = [5, 10, 8]

        for event_time, count in zip(times, counts):
            await generate_events(start_time=event_time, count=count, count_other_team=10)

        batch_export = await create_batch_export()
        result = await run_get_backfill_info(
            batch_export,
            start_at=dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC),
            end_at=dt.datetime(2021, 1, 20, 0, 0, 0, tzinfo=dt.UTC),
        )

        assert result.adjusted_start_at == dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC).isoformat()
        assert result.total_records_count == 10

    async def test_respects_include_events_filter(
        self, ateam, generate_events, create_batch_export, run_get_backfill_info
    ):
        event_time = dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC)
        await generate_events(start_time=event_time, count=20, count_other_team=10, event_name="pageview")
        await generate_events(start_time=event_time, count=30, count_other_team=10, event_name="click")

        batch_export = await create_batch_export(include_events=["pageview"])
        result = await run_get_backfill_info(batch_export, start_at=dt.datetime(2000, 1, 1, tzinfo=dt.UTC))

        assert result.adjusted_start_at is not None
        assert result.total_records_count == 20

    async def test_respects_exclude_events_filter(
        self, ateam, generate_events, create_batch_export, run_get_backfill_info
    ):
        event_time = dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC)
        await generate_events(start_time=event_time, count=20, count_other_team=10, event_name="pageview")
        await generate_events(start_time=event_time, count=30, count_other_team=10, event_name="click")

        batch_export = await create_batch_export(exclude_events=["click"])
        result = await run_get_backfill_info(batch_export, start_at=dt.datetime(2000, 1, 1, tzinfo=dt.UTC))

        assert result.adjusted_start_at is not None
        assert result.total_records_count == 20

    async def test_query_metadata(self, mock_clickhouse_client, run_get_backfill_info, create_batch_export, ateam):
        """Test that the query is executed as expected. This test uses a mocked ClickHouse client to
        verify the query metadata.
        """

        batch_export = await create_batch_export()
        await run_get_backfill_info(
            batch_export,
            start_at=dt.datetime(2021, 1, 1, tzinfo=dt.UTC),
            end_at=dt.datetime(2021, 1, 2, tzinfo=dt.UTC),
        )

        mock_clickhouse_client.expect_query_count(1)
        mock_clickhouse_client.expect_all_calls_have_query_id()
        mock_clickhouse_client.expect_properties_in_log_comment(
            {
                "team_id": ateam.pk,
                "batch_export_id": str(batch_export.id),
                "product": "batch_export",
                "query_type": "backfill_estimate",
            }
        )


class TestGetBackfillInfoForPersons:
    @pytest.fixture(autouse=True)
    async def truncate_persons_tables(self, clickhouse_client):
        await truncate_persons(clickhouse_client)

    @pytest.fixture
    def create_batch_export(self, ateam):
        async def _create(
            interval: str = "hour",
            interval_offset: int | None = None,
            timezone: str = "UTC",
        ) -> BatchExport:
            config = {
                "bucket_name": "test",
                "region": "us-east-1",
                "prefix": "/",
                "aws_access_key_id": "key",
                "aws_secret_access_key": "secret",
            }
            destination = await BatchExportDestination.objects.acreate(type="S3", config=config)
            return await BatchExport.objects.acreate(
                team_id=ateam.pk,
                name="Test Batch Export",
                destination=destination,
                interval=interval,
                interval_offset=interval_offset,
                timezone=timezone,
                model="persons",
            )

        return _create

    @pytest.fixture
    def generate_persons(self, clickhouse_client, ateam):
        async def _generate(
            start_time: dt.datetime,
            end_time: dt.datetime | None = None,
            count: int = 10,
            count_other_team: int = 0,
        ):
            persons, _ = await generate_test_persons_in_clickhouse(
                client=clickhouse_client,
                team_id=ateam.pk,
                start_time=start_time,
                end_time=end_time or start_time + dt.timedelta(hours=1),
                count=count,
                count_other_team=count_other_team,
            )
            return persons

        return _generate

    @pytest.fixture
    def generate_person_distinct_ids(self, clickhouse_client, ateam):
        async def _generate(
            timestamp: dt.datetime,
            count: int = 10,
            person_ids: list[str] | None = None,
        ):
            pdi_values = []
            for i in range(count):
                person_id = uuid.UUID(person_ids[i]) if person_ids and i < len(person_ids) else None
                pdi = generate_test_person_distinct_id2(
                    count=1,
                    team_id=ateam.pk,
                    timestamp=timestamp + dt.timedelta(seconds=i),
                    distinct_id=f"distinct-id-{uuid.uuid4()}",
                    person_id=person_id,
                )
                pdi_values.append(pdi)
            await insert_person_distinct_id2_values_in_clickhouse(client=clickhouse_client, persons=pdi_values)
            return pdi_values

        return _generate

    async def test_returns_earliest_start_and_count_when_data_exists(
        self, ateam, generate_persons, generate_person_distinct_ids, create_batch_export, run_get_backfill_info
    ):
        person_time = dt.datetime(2021, 1, 15, 10, 30, 0, tzinfo=dt.UTC)
        persons = await generate_persons(start_time=person_time, count=5, count_other_team=3)
        person_ids = [p["id"] for p in persons]
        await generate_person_distinct_ids(timestamp=person_time, count=5, person_ids=person_ids)

        batch_export = await create_batch_export()
        result = await run_get_backfill_info(batch_export, start_at=dt.datetime(2000, 1, 1, tzinfo=dt.UTC))

        assert result.adjusted_start_at == dt.datetime(2021, 1, 15, 10, 0, 0, tzinfo=dt.UTC).isoformat()
        assert result.total_records_count == 5

    async def test_returns_count_with_no_adjusted_start_when_start_at_is_none(
        self, ateam, generate_persons, generate_person_distinct_ids, create_batch_export, run_get_backfill_info
    ):
        person_time = dt.datetime(2021, 1, 15, 10, 30, 0, tzinfo=dt.UTC)
        persons = await generate_persons(start_time=person_time, count=5, count_other_team=3)
        person_ids = [p["id"] for p in persons]
        await generate_person_distinct_ids(timestamp=person_time, count=5, person_ids=person_ids)

        batch_export = await create_batch_export()
        result = await run_get_backfill_info(batch_export)

        assert result.adjusted_start_at is None
        assert result.total_records_count == 5

    async def test_returns_zero_when_no_data_exists(self, ateam, create_batch_export, run_get_backfill_info):
        batch_export = await create_batch_export()
        result = await run_get_backfill_info(batch_export)

        assert result.total_records_count == 0

    async def test_takes_minimum_timestamp_across_both_tables(
        self, ateam, generate_persons, generate_person_distinct_ids, create_batch_export, run_get_backfill_info
    ):
        earlier_time = dt.datetime(2021, 1, 10, 5, 0, 0, tzinfo=dt.UTC)
        later_time = dt.datetime(2021, 1, 15, 10, 0, 0, tzinfo=dt.UTC)

        # Persons at later time, distinct_ids at earlier time
        persons = await generate_persons(start_time=later_time, count=3)
        person_ids = [p["id"] for p in persons]
        await generate_person_distinct_ids(timestamp=earlier_time, count=3, person_ids=person_ids)

        batch_export = await create_batch_export()
        result = await run_get_backfill_info(batch_export, start_at=dt.datetime(2000, 1, 1, tzinfo=dt.UTC))

        # Should use the earlier timestamp from person_distinct_id2
        assert result.adjusted_start_at == dt.datetime(2021, 1, 10, 5, 0, 0, tzinfo=dt.UTC).isoformat()

    async def test_count_includes_distinct_ids_from_changed_persons(
        self, ateam, clickhouse_client, generate_person_distinct_ids, create_batch_export, run_get_backfill_info
    ):
        """When a person changes, all their existing distinct_ids should be counted."""
        old_time = dt.datetime(2021, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
        new_time = dt.datetime(2021, 1, 15, 10, 30, 0, tzinfo=dt.UTC)

        person_id = uuid.uuid4()

        # Insert person at old time (version 1) and new time (version 2)
        await insert_person_values_in_clickhouse(
            client=clickhouse_client,
            persons=[
                {
                    "id": str(person_id),
                    "created_at": old_time.strftime("%Y-%m-%d %H:%M:%S.%f"),
                    "team_id": ateam.pk,
                    "properties": None,
                    "is_identified": True,
                    "is_deleted": False,
                    "version": 1,
                    "_timestamp": old_time.strftime("%Y-%m-%d %H:%M:%S"),
                },
                {
                    "id": str(person_id),
                    "created_at": old_time.strftime("%Y-%m-%d %H:%M:%S.%f"),
                    "team_id": ateam.pk,
                    "properties": None,
                    "is_identified": True,
                    "is_deleted": False,
                    "version": 2,
                    "_timestamp": new_time.strftime("%Y-%m-%d %H:%M:%S"),
                },
            ],
        )

        # Create 3 distinct_ids for this person at old time (not in the query range)
        await generate_person_distinct_ids(timestamp=old_time, count=3, person_ids=[str(person_id)] * 3)

        batch_export = await create_batch_export()
        # Query range only covers new_time — person changed but distinct_ids didn't
        result = await run_get_backfill_info(
            batch_export,
            start_at=dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC),
            end_at=dt.datetime(2021, 1, 16, 0, 0, 0, tzinfo=dt.UTC),
        )

        # All 3 distinct_ids should be counted via the UNION DISTINCT branch
        assert result.total_records_count == 3

    async def test_count_deduplicates_by_latest_version(
        self, ateam, clickhouse_client, create_batch_export, run_get_backfill_info
    ):
        """Only count distinct_ids/persons whose latest version is in range."""
        old_time = dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC)
        new_time = dt.datetime(2021, 1, 20, 0, 0, 0, tzinfo=dt.UTC)

        distinct_id = f"distinct-id-{uuid.uuid4()}"
        person_id = uuid.uuid4()

        # Insert person with v1 in range and v2 outside range
        await insert_person_values_in_clickhouse(
            client=clickhouse_client,
            persons=[
                {
                    "id": str(person_id),
                    "created_at": old_time.strftime("%Y-%m-%d %H:%M:%S.%f"),
                    "team_id": ateam.pk,
                    "properties": None,
                    "is_identified": True,
                    "is_deleted": False,
                    "version": 1,
                    "_timestamp": old_time.strftime("%Y-%m-%d %H:%M:%S"),
                },
                {
                    "id": str(person_id),
                    "created_at": old_time.strftime("%Y-%m-%d %H:%M:%S.%f"),
                    "team_id": ateam.pk,
                    "properties": None,
                    "is_identified": True,
                    "is_deleted": False,
                    "version": 2,
                    "_timestamp": new_time.strftime("%Y-%m-%d %H:%M:%S"),
                },
            ],
        )

        # Insert distinct_id with v1 in range and v2 outside range
        await insert_person_distinct_id2_values_in_clickhouse(
            client=clickhouse_client,
            persons=[
                {
                    "team_id": ateam.pk,
                    "distinct_id": distinct_id,
                    "person_id": str(person_id),
                    "is_deleted": False,
                    "version": 1,
                    "_timestamp": old_time.strftime("%Y-%m-%d %H:%M:%S"),
                },
                {
                    "team_id": ateam.pk,
                    "distinct_id": distinct_id,
                    "person_id": str(person_id),
                    "is_deleted": False,
                    "version": 2,
                    "_timestamp": new_time.strftime("%Y-%m-%d %H:%M:%S"),
                },
            ],
        )

        batch_export = await create_batch_export()

        # Query range covers only old_time — but latest versions are at new_time for both
        result = await run_get_backfill_info(
            batch_export,
            start_at=dt.datetime(2021, 1, 5, 0, 0, 0, tzinfo=dt.UTC),
            end_at=dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC),
        )

        # Neither person nor distinct_id has latest version in range, so count should be 0
        assert result.total_records_count == 0

    async def test_counts_only_records_after_start_at(
        self, ateam, generate_persons, generate_person_distinct_ids, create_batch_export, run_get_backfill_info
    ):
        early_time = dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC)
        late_time = dt.datetime(2021, 1, 20, 0, 0, 0, tzinfo=dt.UTC)

        early_persons = await generate_persons(start_time=early_time, count=5)
        await generate_person_distinct_ids(timestamp=early_time, count=5, person_ids=[p["id"] for p in early_persons])

        late_persons = await generate_persons(start_time=late_time, count=8)
        await generate_person_distinct_ids(timestamp=late_time, count=8, person_ids=[p["id"] for p in late_persons])

        batch_export = await create_batch_export()
        result = await run_get_backfill_info(
            batch_export,
            start_at=dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC),
        )

        assert result.adjusted_start_at == dt.datetime(2021, 1, 20, 0, 0, 0, tzinfo=dt.UTC).isoformat()
        assert result.total_records_count == 8

    async def test_counts_only_records_before_end_at(
        self, ateam, generate_persons, generate_person_distinct_ids, create_batch_export, run_get_backfill_info
    ):
        early_time = dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC)
        late_time = dt.datetime(2021, 1, 20, 0, 0, 0, tzinfo=dt.UTC)

        early_persons = await generate_persons(start_time=early_time, count=5)
        await generate_person_distinct_ids(timestamp=early_time, count=5, person_ids=[p["id"] for p in early_persons])

        late_persons = await generate_persons(start_time=late_time, count=8)
        await generate_person_distinct_ids(timestamp=late_time, count=8, person_ids=[p["id"] for p in late_persons])

        batch_export = await create_batch_export()
        result = await run_get_backfill_info(
            batch_export,
            start_at=dt.datetime(2000, 1, 1, tzinfo=dt.UTC),
            end_at=dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC),
        )

        assert result.adjusted_start_at == dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC).isoformat()
        assert result.total_records_count == 5

    async def test_counts_only_records_in_range(
        self, ateam, generate_persons, generate_person_distinct_ids, create_batch_export, run_get_backfill_info
    ):
        times = [
            dt.datetime(2021, 1, 5, 0, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2021, 1, 25, 0, 0, 0, tzinfo=dt.UTC),
        ]
        counts = [3, 7, 4]

        for time, count in zip(times, counts):
            persons = await generate_persons(start_time=time, count=count)
            await generate_person_distinct_ids(timestamp=time, count=count, person_ids=[p["id"] for p in persons])

        batch_export = await create_batch_export()
        result = await run_get_backfill_info(
            batch_export,
            start_at=dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC),
            end_at=dt.datetime(2021, 1, 20, 0, 0, 0, tzinfo=dt.UTC),
        )

        assert result.adjusted_start_at == dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC).isoformat()
        assert result.total_records_count == 7

    async def test_ignores_data_from_other_teams(
        self, ateam, generate_persons, create_batch_export, run_get_backfill_info
    ):
        person_time = dt.datetime(2021, 1, 15, 10, 30, 0, tzinfo=dt.UTC)
        # Generate persons for this team AND other team — only other team data
        await generate_persons(start_time=person_time, count=0, count_other_team=10)

        batch_export = await create_batch_export()
        result = await run_get_backfill_info(batch_export)

        assert result.total_records_count == 0

    async def test_query_metadata_when_no_data(
        self, mock_clickhouse_client, run_get_backfill_info, create_batch_export, ateam
    ):
        """Persons model runs min_timestamp query first; if no data, skips the count query."""
        batch_export = await create_batch_export()
        await run_get_backfill_info(
            batch_export,
            start_at=dt.datetime(2021, 1, 1, tzinfo=dt.UTC),
            end_at=dt.datetime(2021, 1, 2, tzinfo=dt.UTC),
        )

        mock_clickhouse_client.expect_query_count(1)
        mock_clickhouse_client.expect_all_calls_have_query_id()
        mock_clickhouse_client.expect_properties_in_log_comment(
            {
                "team_id": ateam.pk,
                "batch_export_id": str(batch_export.id),
                "product": "batch_export",
                "query_type": "backfill_estimate",
            }
        )

    async def test_executes_two_queries_when_data_exists(
        self, mock_clickhouse_client, run_get_backfill_info, create_batch_export, ateam
    ):
        """Persons model runs both min_timestamp and count queries when data exists."""
        batch_export = await create_batch_export()

        mock_clickhouse_client.read_query_as_jsonl_responses = [
            [{"min_timestamp": "2021-01-15 10:30:00"}, {"min_timestamp": "2021-01-15 10:30:00"}],
            [{"record_count": "42"}],
        ]

        await run_get_backfill_info(
            batch_export,
            start_at=dt.datetime(2021, 1, 1, tzinfo=dt.UTC),
            end_at=dt.datetime(2021, 1, 2, tzinfo=dt.UTC),
        )

        mock_clickhouse_client.expect_query_count(2)
        mock_clickhouse_client.expect_unique_query_ids()
        mock_clickhouse_client.expect_properties_in_log_comment({"query_type": "backfill_estimate"})


class TestGetBackfillInfoForSessions:
    @pytest.fixture(autouse=True)
    async def truncate_tables(self, clickhouse_client):
        await truncate_events(clickhouse_client)
        await truncate_sessions(clickhouse_client)

    @pytest.fixture
    def create_batch_export(self, ateam):
        async def _create(
            interval: str = "hour",
            interval_offset: int | None = None,
            timezone: str = "UTC",
        ) -> BatchExport:
            config = {
                "bucket_name": "test",
                "region": "us-east-1",
                "prefix": "/",
                "aws_access_key_id": "key",
                "aws_secret_access_key": "secret",
            }
            destination = await BatchExportDestination.objects.acreate(type="S3", config=config)
            return await BatchExport.objects.acreate(
                team_id=ateam.pk,
                name="Test Batch Export",
                destination=destination,
                interval=interval,
                interval_offset=interval_offset,
                timezone=timezone,
                model="sessions",
            )

        return _create

    @pytest.fixture
    def generate_sessions(self, clickhouse_client, ateam):
        async def _generate(
            start_time: dt.datetime,
            end_time: dt.datetime | None = None,
            count: int = 10,
            count_other_team: int = 0,
        ):
            """Generate events with unique session IDs and derive sessions from them.

            Each event gets a unique $session_id, so the number of sessions equals count.
            """
            for i in range(count):
                event_time = start_time + dt.timedelta(seconds=i)
                session_id = str(uuid7(unix_ms_time=int(event_time.timestamp() * 1000)))
                await generate_test_events_in_clickhouse(
                    client=clickhouse_client,
                    team_id=ateam.pk,
                    start_time=event_time,
                    end_time=(end_time or event_time + dt.timedelta(minutes=2)),
                    count=1,
                    inserted_at=event_time,
                    table="sharded_events",
                    event_name="test-event",
                    count_outside_range=0,
                    count_other_team=0,
                    properties={"$session_id": session_id},
                )

            for i in range(count_other_team):
                event_time = start_time + dt.timedelta(seconds=i)
                session_id = str(uuid7(unix_ms_time=int(event_time.timestamp() * 1000)))
                await generate_test_events_in_clickhouse(
                    client=clickhouse_client,
                    team_id=ateam.pk + 1,
                    start_time=event_time,
                    end_time=(end_time or event_time + dt.timedelta(minutes=2)),
                    count=1,
                    inserted_at=event_time,
                    table="sharded_events",
                    event_name="test-event",
                    count_outside_range=0,
                    count_other_team=0,
                    properties={"$session_id": session_id},
                )

            await insert_sessions_in_clickhouse(client=clickhouse_client, table="sharded_events")

        return _generate

    async def test_returns_earliest_start_and_count_when_data_exists(
        self, generate_sessions, create_batch_export, run_get_backfill_info
    ):
        session_time = dt.datetime(2021, 1, 15, 10, 30, 0, tzinfo=dt.UTC)
        await generate_sessions(start_time=session_time, count=5, count_other_team=3)

        batch_export = await create_batch_export()
        result = await run_get_backfill_info(batch_export, start_at=dt.datetime(2000, 1, 1, tzinfo=dt.UTC))

        assert result.adjusted_start_at == dt.datetime(2021, 1, 15, 10, 0, 0, tzinfo=dt.UTC).isoformat()
        assert result.total_records_count == 5

    async def test_returns_count_with_no_adjusted_start_when_start_at_is_none(
        self, generate_sessions, create_batch_export, run_get_backfill_info
    ):
        session_time = dt.datetime(2021, 1, 15, 10, 30, 0, tzinfo=dt.UTC)
        await generate_sessions(start_time=session_time, count=5, count_other_team=3)

        batch_export = await create_batch_export()
        result = await run_get_backfill_info(batch_export)

        assert result.adjusted_start_at is None
        assert result.total_records_count == 5

    async def test_returns_zero_when_no_data_exists(self, create_batch_export, run_get_backfill_info):
        batch_export = await create_batch_export()
        result = await run_get_backfill_info(batch_export)

        assert result.total_records_count == 0

    async def test_counts_only_sessions_after_start_at(
        self, generate_sessions, create_batch_export, run_get_backfill_info
    ):
        early_time = dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC)
        late_time = dt.datetime(2021, 1, 20, 0, 0, 0, tzinfo=dt.UTC)

        await generate_sessions(start_time=early_time, count=5)
        await generate_sessions(start_time=late_time, count=8)

        batch_export = await create_batch_export()
        result = await run_get_backfill_info(
            batch_export,
            start_at=dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC),
        )

        assert result.adjusted_start_at == dt.datetime(2021, 1, 20, 0, 0, 0, tzinfo=dt.UTC).isoformat()
        assert result.total_records_count == 8

    async def test_counts_only_sessions_before_end_at(
        self, generate_sessions, create_batch_export, run_get_backfill_info
    ):
        early_time = dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC)
        late_time = dt.datetime(2021, 1, 20, 0, 0, 0, tzinfo=dt.UTC)

        await generate_sessions(start_time=early_time, count=5)
        await generate_sessions(start_time=late_time, count=8)

        batch_export = await create_batch_export()
        result = await run_get_backfill_info(
            batch_export,
            start_at=dt.datetime(2000, 1, 1, tzinfo=dt.UTC),
            end_at=dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC),
        )

        assert result.adjusted_start_at == dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC).isoformat()
        assert result.total_records_count == 5

    async def test_query_metadata(self, mock_clickhouse_client, run_get_backfill_info, create_batch_export, ateam):
        """Test that the query is executed as expected. This test uses a mocked ClickHouse client to verify the query metadata."""
        batch_export = await create_batch_export()
        await run_get_backfill_info(
            batch_export,
            start_at=dt.datetime(2021, 1, 1, tzinfo=dt.UTC),
            end_at=dt.datetime(2021, 1, 2, tzinfo=dt.UTC),
        )

        mock_clickhouse_client.expect_query_count(1)
        mock_clickhouse_client.expect_all_calls_have_query_id()
        mock_clickhouse_client.expect_properties_in_log_comment(
            {
                "team_id": ateam.pk,
                "batch_export_id": str(batch_export.id),
                "product": "batch_export",
                "query_type": "backfill_estimate",
            }
        )
