import uuid
import datetime as dt

import pytest

from posthog.batch_exports.models import BatchExport, BatchExportDestination
from posthog.models.utils import uuid7
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse, insert_sessions_in_clickhouse

from products.batch_exports.backend.temporal.backfill_batch_export import (
    _get_backfill_info_for_events,
    _get_backfill_info_for_persons,
    _get_backfill_info_for_sessions,
)
from products.batch_exports.backend.tests.temporal.utils.clickhouse import (
    truncate_events,
    truncate_persons,
    truncate_sessions,
)
from products.batch_exports.backend.tests.temporal.utils.persons import (
    generate_test_person_distinct_id2,
    generate_test_persons_in_clickhouse,
    insert_person_distinct_id2_values_in_clickhouse,
    insert_person_values_in_clickhouse,
)


class TestGetBackfillInfoForEvents:
    """Tests for the _get_backfill_info_for_events function."""

    @pytest.fixture(autouse=True)
    async def truncate_events_table(self, clickhouse_client):
        """Fixture to truncate events table before each test."""
        await truncate_events(clickhouse_client)

    @pytest.fixture
    def make_batch_export(self, ateam):
        """Factory fixture to create BatchExport objects (not saved to DB)."""

        def _make(
            interval: str = "hour",
            interval_offset: int | None = None,
            timezone: str = "UTC",
        ) -> BatchExport:
            destination = BatchExportDestination(type="S3", config={})
            return BatchExport(
                team_id=ateam.pk,
                name="Test Batch Export",
                destination=destination,
                interval=interval,
                interval_offset=interval_offset,
                timezone=timezone,
            )

        return _make

    async def test_returns_earliest_start_and_count_when_data_exists(self, ateam, generate_events, make_batch_export):
        """Test basic case: returns earliest_start and record_count when events exist."""
        event_time = dt.datetime(2021, 1, 15, 10, 30, 0, tzinfo=dt.UTC)
        await generate_events(start_time=event_time, count=25, count_other_team=10)

        batch_export = make_batch_export()
        earliest_start, record_count = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
            include_events=[],
            exclude_events=[],
            filters_str="",
            extra_query_parameters={},
        )

        assert earliest_start == dt.datetime(2021, 1, 15, 10, 0, 0, tzinfo=dt.UTC)
        assert record_count == 25

    async def test_returns_none_and_zero_when_no_data_exists(self, ateam, make_batch_export):
        """Test that (None, 0) is returned when no events exist for the team."""
        batch_export = make_batch_export()
        earliest_start, record_count = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
            include_events=[],
            exclude_events=[],
            filters_str="",
            extra_query_parameters={},
        )

        assert earliest_start is None
        assert record_count == 0

    async def test_counts_only_events_after_start_at(self, ateam, generate_events, make_batch_export):
        """Test that count respects start_at filter."""
        early_time = dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC)
        late_time = dt.datetime(2021, 1, 20, 0, 0, 0, tzinfo=dt.UTC)

        await generate_events(start_time=early_time, count=10, count_other_team=10)
        await generate_events(start_time=late_time, count=15, count_other_team=10)

        batch_export = make_batch_export()
        earliest_start, record_count = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC),
            end_at=None,
            include_events=[],
            exclude_events=[],
            filters_str="",
            extra_query_parameters={},
        )

        # earliest_start should be the earliest event within the date range
        assert earliest_start == dt.datetime(2021, 1, 20, 0, 0, 0, tzinfo=dt.UTC)
        # count should only include events after start_at
        assert record_count == 15

    async def test_counts_only_events_before_end_at(self, ateam, generate_events, make_batch_export):
        """Test that count respects end_at filter."""
        early_time = dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC)
        late_time = dt.datetime(2021, 1, 20, 0, 0, 0, tzinfo=dt.UTC)

        await generate_events(start_time=early_time, count=10, count_other_team=10)
        await generate_events(start_time=late_time, count=15, count_other_team=10)

        batch_export = make_batch_export()
        earliest_start, record_count = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=None,
            end_at=dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC),
            include_events=[],
            exclude_events=[],
            filters_str="",
            extra_query_parameters={},
        )

        # earliest_start should be the earliest event within the date range
        assert earliest_start == dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC)
        # count should only include events before end_at
        assert record_count == 10

    async def test_counts_only_events_in_range(self, ateam, generate_events, make_batch_export):
        """Test that count respects both start_at and end_at filters."""
        times = [
            dt.datetime(2021, 1, 5, 0, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2021, 1, 25, 0, 0, 0, tzinfo=dt.UTC),
        ]
        counts = [5, 10, 8]

        for event_time, count in zip(times, counts):
            await generate_events(start_time=event_time, count=count, count_other_team=10)

        batch_export = make_batch_export()
        earliest_start, record_count = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC),
            end_at=dt.datetime(2021, 1, 20, 0, 0, 0, tzinfo=dt.UTC),
            include_events=[],
            exclude_events=[],
            filters_str="",
            extra_query_parameters={},
        )

        # earliest_start should be the earliest event within the date range
        assert earliest_start == dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC)
        # count should only include the middle batch (10 events)
        assert record_count == 10

    async def test_respects_include_events_filter(self, ateam, generate_events, make_batch_export):
        """Test that include_events filter is respected."""
        event_time = dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC)
        await generate_events(start_time=event_time, count=20, count_other_team=10, event_name="pageview")
        await generate_events(start_time=event_time, count=30, count_other_team=10, event_name="click")

        batch_export = make_batch_export()
        earliest_start, record_count = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
            include_events=["pageview"],
            exclude_events=[],
            filters_str="",
            extra_query_parameters={},
        )

        assert earliest_start is not None
        assert record_count == 20

    async def test_respects_exclude_events_filter(self, ateam, generate_events, make_batch_export):
        """Test that exclude_events filter is respected."""
        event_time = dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC)
        await generate_events(start_time=event_time, count=20, count_other_team=10, event_name="pageview")
        await generate_events(start_time=event_time, count=30, count_other_team=10, event_name="click")

        batch_export = make_batch_export()
        earliest_start, record_count = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
            include_events=[],
            exclude_events=["click"],
            filters_str="",
            extra_query_parameters={},
        )

        assert earliest_start is not None
        assert record_count == 20

    async def test_earliest_start_aligned_to_interval(self, ateam, generate_events, make_batch_export):
        """Test that earliest_start is aligned to the interval boundary."""
        event_time = dt.datetime(2021, 1, 15, 10, 37, 45, tzinfo=dt.UTC)
        await generate_events(
            start_time=event_time, count=5, end_time=event_time + dt.timedelta(minutes=1), count_other_team=10
        )

        # Hourly interval - should align to 10:00
        batch_export = make_batch_export(interval="hour")
        earliest_start, _ = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
            include_events=[],
            exclude_events=[],
            filters_str="",
            extra_query_parameters={},
        )
        assert earliest_start == dt.datetime(2021, 1, 15, 10, 0, 0, tzinfo=dt.UTC)

        # 5-minute interval - should align to 10:35
        batch_export = make_batch_export(interval="every 5 minutes")
        earliest_start, _ = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
            include_events=[],
            exclude_events=[],
            filters_str="",
            extra_query_parameters={},
        )
        assert earliest_start == dt.datetime(2021, 1, 15, 10, 35, 0, tzinfo=dt.UTC)

    async def test_custom_filters_str_is_applied(self, ateam, generate_events, make_batch_export):
        """Test that custom filters_str is included in the query."""
        event_time = dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC)
        await generate_events(start_time=event_time, count=50, count_other_team=10)

        # Apply a filter that excludes all events
        batch_export = make_batch_export()
        earliest_start, record_count = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
            include_events=[],
            exclude_events=[],
            filters_str="AND 1 = 0",
            extra_query_parameters={},
        )

        assert earliest_start is None
        assert record_count == 0

    async def test_earliest_start_respects_interval_offset_daily(self, ateam, generate_events, make_batch_export):
        """Test that earliest_start respects interval_offset for daily exports.

        For a daily export with offset_hour=5 (interval_offset=18000):
        - 10:30am aligns to 5am same day
        - 4:30am aligns to 5am previous day
        """
        # Event at 10:30am on Jan 15 should align to 5am Jan 15
        event_time = dt.datetime(2021, 1, 15, 10, 30, 0, tzinfo=dt.UTC)
        await generate_events(start_time=event_time, count=5, end_time=event_time + dt.timedelta(minutes=1))

        # Daily interval with offset_hour=5 (18000s offset)
        batch_export = make_batch_export(interval="day", interval_offset=5 * 3600)
        earliest_start, _ = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
            include_events=[],
            exclude_events=[],
            filters_str="",
            extra_query_parameters={},
        )
        assert earliest_start == dt.datetime(2021, 1, 15, 5, 0, 0, tzinfo=dt.UTC)

    async def test_earliest_start_respects_interval_offset_daily_before_offset(
        self, ateam, generate_events, make_batch_export
    ):
        """Test that earliest_start correctly aligns when event is before offset hour.

        For a daily export with offset_hour=5:
        - Event at 4:30am should align to 5am the PREVIOUS day
        """
        # Event at 4:30am on Jan 15 should align to 5am Jan 14
        event_time = dt.datetime(2021, 1, 15, 4, 30, 0, tzinfo=dt.UTC)
        await generate_events(start_time=event_time, count=5, end_time=event_time + dt.timedelta(minutes=1))

        # Daily interval with offset_hour=5 (18000s offset)
        batch_export = make_batch_export(interval="day", interval_offset=5 * 3600)
        earliest_start, _ = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
            include_events=[],
            exclude_events=[],
            filters_str="",
            extra_query_parameters={},
        )
        # Event is before 5am, so it falls in the previous day's interval starting at 5am
        assert earliest_start == dt.datetime(2021, 1, 14, 5, 0, 0, tzinfo=dt.UTC)

    async def test_earliest_start_respects_interval_offset_weekly(self, ateam, generate_events, make_batch_export):
        """Test that earliest_start respects interval_offset for weekly exports.

        For a weekly export starting Monday at 5am (offset_day=1, offset_hour=5):
        - An event on Thursday at 10am should align to Monday 5am of that week
        """
        # Thursday Jan 14, 2021 at 10am (Monday was Jan 11)
        event_time = dt.datetime(2021, 1, 14, 10, 0, 0, tzinfo=dt.UTC)
        await generate_events(start_time=event_time, count=5, end_time=event_time + dt.timedelta(minutes=1))

        # Weekly interval with offset_day=1 (Monday) and offset_hour=5
        # offset = 1 * 86400 + 5 * 3600 = 86400 + 18000 = 104400
        batch_export = make_batch_export(interval="week", interval_offset=1 * 86400 + 5 * 3600)
        earliest_start, _ = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
            include_events=[],
            exclude_events=[],
            filters_str="",
            extra_query_parameters={},
        )
        # Monday Jan 11, 2021 at 5am UTC
        assert earliest_start == dt.datetime(2021, 1, 11, 5, 0, 0, tzinfo=dt.UTC)

    async def test_earliest_start_respects_timezone_us_pacific(self, ateam, generate_events, make_batch_export):
        """Test that earliest_start respects timezone for daily exports.

        For a daily export at 1am US/Pacific:
        - In January (PST = UTC-8), 1am Pacific = 9am UTC
        - An event at 10:00 UTC (2:00am PST) should align to 9:00 UTC (1:00am PST)
        - An event at 08:30 UTC (0:30am PST) should align to previous day's 9:00 UTC
        """
        # Event at 10:00 UTC on Jan 15 (which is 2:00am PST on Jan 15)
        event_time = dt.datetime(2021, 1, 15, 10, 0, 0, tzinfo=dt.UTC)
        await generate_events(start_time=event_time, count=5, end_time=event_time + dt.timedelta(minutes=1))

        # Daily interval at 1am US/Pacific (offset_hour=1)
        batch_export = make_batch_export(interval="day", interval_offset=1 * 3600, timezone="US/Pacific")
        earliest_start, _ = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
            include_events=[],
            exclude_events=[],
            filters_str="",
            extra_query_parameters={},
        )
        # 1am PST on Jan 15 = 9am UTC on Jan 15
        assert earliest_start == dt.datetime(2021, 1, 15, 9, 0, 0, tzinfo=dt.UTC)

    async def test_earliest_start_respects_timezone_before_offset_hour(self, ateam, generate_events, make_batch_export):
        """Test that earliest_start aligns to previous day when event is before offset hour in local time.

        For a daily export at 1am US/Pacific:
        - An event at 08:30 UTC (0:30am PST) should align to previous day's 1am PST = 9am UTC
        """
        # Event at 08:30 UTC on Jan 15 (which is 0:30am PST on Jan 15, before 1am)
        event_time = dt.datetime(2021, 1, 15, 8, 30, 0, tzinfo=dt.UTC)
        await generate_events(start_time=event_time, count=5, end_time=event_time + dt.timedelta(minutes=1))

        # Daily interval at 1am US/Pacific (offset_hour=1)
        batch_export = make_batch_export(interval="day", interval_offset=1 * 3600, timezone="US/Pacific")
        earliest_start, _ = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
            include_events=[],
            exclude_events=[],
            filters_str="",
            extra_query_parameters={},
        )
        # Event is before 1am PST, so it falls in previous day's interval
        # 1am PST on Jan 14 = 9am UTC on Jan 14
        assert earliest_start == dt.datetime(2021, 1, 14, 9, 0, 0, tzinfo=dt.UTC)


class TestGetBackfillInfoForPersons:
    """Tests for the _get_backfill_info_for_persons function."""

    @pytest.fixture(autouse=True)
    async def truncate_persons_tables(self, clickhouse_client):
        await truncate_persons(clickhouse_client)

    @pytest.fixture
    def make_batch_export(self, ateam):
        def _make(
            interval: str = "hour",
            interval_offset: int | None = None,
            timezone: str = "UTC",
        ) -> BatchExport:
            destination = BatchExportDestination(type="S3", config={})
            return BatchExport(
                team_id=ateam.pk,
                name="Test Batch Export",
                destination=destination,
                interval=interval,
                interval_offset=interval_offset,
                timezone=timezone,
                model="persons",
            )

        return _make

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
        self, ateam, generate_persons, generate_person_distinct_ids, make_batch_export
    ):
        person_time = dt.datetime(2021, 1, 15, 10, 30, 0, tzinfo=dt.UTC)
        persons = await generate_persons(start_time=person_time, count=5, count_other_team=3)
        person_ids = [p["id"] for p in persons]
        await generate_person_distinct_ids(timestamp=person_time, count=5, person_ids=person_ids)

        batch_export = make_batch_export()
        earliest_start, record_count = await _get_backfill_info_for_persons(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
        )

        assert earliest_start == dt.datetime(2021, 1, 15, 10, 0, 0, tzinfo=dt.UTC)
        assert record_count == 5

    async def test_returns_none_and_zero_when_no_data_exists(self, ateam, make_batch_export):
        batch_export = make_batch_export()
        earliest_start, record_count = await _get_backfill_info_for_persons(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
        )

        assert earliest_start is None
        assert record_count == 0

    async def test_takes_minimum_timestamp_across_both_tables(
        self, ateam, generate_persons, generate_person_distinct_ids, make_batch_export
    ):
        earlier_time = dt.datetime(2021, 1, 10, 5, 0, 0, tzinfo=dt.UTC)
        later_time = dt.datetime(2021, 1, 15, 10, 0, 0, tzinfo=dt.UTC)

        # Persons at later time, distinct_ids at earlier time
        persons = await generate_persons(start_time=later_time, count=3)
        person_ids = [p["id"] for p in persons]
        await generate_person_distinct_ids(timestamp=earlier_time, count=3, person_ids=person_ids)

        batch_export = make_batch_export()
        earliest_start, _ = await _get_backfill_info_for_persons(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
        )

        # Should use the earlier timestamp from person_distinct_id2
        assert earliest_start == dt.datetime(2021, 1, 10, 5, 0, 0, tzinfo=dt.UTC)

    async def test_count_includes_distinct_ids_from_changed_persons(
        self, ateam, clickhouse_client, generate_person_distinct_ids, make_batch_export
    ):
        """When a person changes, all their existing distinct_ids should be counted."""
        # Create a person with 3 distinct_ids at an old timestamp
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

        batch_export = make_batch_export()
        # Query range only covers new_time — person changed but distinct_ids didn't
        _, record_count = await _get_backfill_info_for_persons(
            batch_export=batch_export,
            start_at=dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC),
            end_at=dt.datetime(2021, 1, 16, 0, 0, 0, tzinfo=dt.UTC),
        )

        # All 3 distinct_ids should be counted via the UNION DISTINCT branch
        assert record_count == 3

    async def test_count_deduplicates_by_latest_version(self, ateam, clickhouse_client, make_batch_export):
        """Only count distinct_ids/persons whose latest version is in range."""

        old_time = dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC)
        new_time = dt.datetime(2021, 1, 20, 0, 0, 0, tzinfo=dt.UTC)

        distinct_id = f"distinct-id-{uuid.uuid4()}"
        person_id = uuid.uuid4()

        # Insert person with v1 in range and v2 outside range
        # argMax(_timestamp, version) will return new_time (v2), which is outside the query range
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

        batch_export = make_batch_export()

        # Query range covers only old_time — but latest versions are at new_time for both
        _, record_count = await _get_backfill_info_for_persons(
            batch_export=batch_export,
            start_at=dt.datetime(2021, 1, 5, 0, 0, 0, tzinfo=dt.UTC),
            end_at=dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC),
        )

        # Neither person nor distinct_id has latest version in range, so count should be 0
        assert record_count == 0

    async def test_counts_only_records_after_start_at(
        self, ateam, generate_persons, generate_person_distinct_ids, make_batch_export
    ):
        early_time = dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC)
        late_time = dt.datetime(2021, 1, 20, 0, 0, 0, tzinfo=dt.UTC)

        early_persons = await generate_persons(start_time=early_time, count=5)
        await generate_person_distinct_ids(timestamp=early_time, count=5, person_ids=[p["id"] for p in early_persons])

        late_persons = await generate_persons(start_time=late_time, count=8)
        await generate_person_distinct_ids(timestamp=late_time, count=8, person_ids=[p["id"] for p in late_persons])

        batch_export = make_batch_export()
        earliest_start, record_count = await _get_backfill_info_for_persons(
            batch_export=batch_export,
            start_at=dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC),
            end_at=None,
        )

        assert earliest_start == dt.datetime(2021, 1, 20, 0, 0, 0, tzinfo=dt.UTC)
        assert record_count == 8

    async def test_counts_only_records_before_end_at(
        self, ateam, generate_persons, generate_person_distinct_ids, make_batch_export
    ):
        early_time = dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC)
        late_time = dt.datetime(2021, 1, 20, 0, 0, 0, tzinfo=dt.UTC)

        early_persons = await generate_persons(start_time=early_time, count=5)
        await generate_person_distinct_ids(timestamp=early_time, count=5, person_ids=[p["id"] for p in early_persons])

        late_persons = await generate_persons(start_time=late_time, count=8)
        await generate_person_distinct_ids(timestamp=late_time, count=8, person_ids=[p["id"] for p in late_persons])

        batch_export = make_batch_export()
        earliest_start, record_count = await _get_backfill_info_for_persons(
            batch_export=batch_export,
            start_at=None,
            end_at=dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC),
        )

        assert earliest_start == dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC)
        assert record_count == 5

    async def test_counts_only_records_in_range(
        self, ateam, generate_persons, generate_person_distinct_ids, make_batch_export
    ):
        times = [
            dt.datetime(2021, 1, 5, 0, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2021, 1, 25, 0, 0, 0, tzinfo=dt.UTC),
        ]
        counts = [3, 7, 4]

        for t, c in zip(times, counts):
            persons = await generate_persons(start_time=t, count=c)
            await generate_person_distinct_ids(timestamp=t, count=c, person_ids=[p["id"] for p in persons])

        batch_export = make_batch_export()
        earliest_start, record_count = await _get_backfill_info_for_persons(
            batch_export=batch_export,
            start_at=dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC),
            end_at=dt.datetime(2021, 1, 20, 0, 0, 0, tzinfo=dt.UTC),
        )

        assert earliest_start == dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC)
        assert record_count == 7

    async def test_earliest_start_aligned_to_interval(
        self, ateam, generate_persons, generate_person_distinct_ids, make_batch_export
    ):
        person_time = dt.datetime(2021, 1, 15, 10, 37, 45, tzinfo=dt.UTC)
        persons = await generate_persons(
            start_time=person_time, count=3, end_time=person_time + dt.timedelta(minutes=1)
        )
        await generate_person_distinct_ids(timestamp=person_time, count=3, person_ids=[p["id"] for p in persons])

        # Hourly interval — should align to 10:00
        batch_export = make_batch_export(interval="hour")
        earliest_start, _ = await _get_backfill_info_for_persons(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
        )
        assert earliest_start == dt.datetime(2021, 1, 15, 10, 0, 0, tzinfo=dt.UTC)

        # 5-minute interval — should align to 10:35
        batch_export = make_batch_export(interval="every 5 minutes")
        earliest_start, _ = await _get_backfill_info_for_persons(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
        )
        assert earliest_start == dt.datetime(2021, 1, 15, 10, 35, 0, tzinfo=dt.UTC)

    async def test_ignores_data_from_other_teams(
        self, ateam, generate_persons, generate_person_distinct_ids, make_batch_export
    ):
        person_time = dt.datetime(2021, 1, 15, 10, 30, 0, tzinfo=dt.UTC)
        # Generate persons for this team AND other team — only other team data
        await generate_persons(start_time=person_time, count=0, count_other_team=10)

        batch_export = make_batch_export()
        earliest_start, record_count = await _get_backfill_info_for_persons(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
        )

        assert earliest_start is None
        assert record_count == 0


class TestGetBackfillInfoForSessions:
    """Tests for the _get_backfill_info_for_sessions function."""

    @pytest.fixture(autouse=True)
    async def truncate_tables(self, clickhouse_client):
        await truncate_events(clickhouse_client)
        await truncate_sessions(clickhouse_client)

    @pytest.fixture
    def make_batch_export(self, ateam):
        def _make(
            interval: str = "hour",
            interval_offset: int | None = None,
            timezone: str = "UTC",
        ) -> BatchExport:
            destination = BatchExportDestination(type="S3", config={})
            return BatchExport(
                team_id=ateam.pk,
                name="Test Batch Export",
                destination=destination,
                interval=interval,
                interval_offset=interval_offset,
                timezone=timezone,
                model="sessions",
            )

        return _make

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

    async def test_returns_earliest_start_and_count_when_data_exists(self, generate_sessions, make_batch_export):
        session_time = dt.datetime(2021, 1, 15, 10, 30, 0, tzinfo=dt.UTC)
        await generate_sessions(start_time=session_time, count=5, count_other_team=3)

        batch_export = make_batch_export()
        earliest_start, record_count = await _get_backfill_info_for_sessions(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
        )

        assert earliest_start == dt.datetime(2021, 1, 15, 10, 0, 0, tzinfo=dt.UTC)
        assert record_count == 5

    async def test_returns_none_and_zero_when_no_data_exists(self, make_batch_export):
        batch_export = make_batch_export()
        earliest_start, record_count = await _get_backfill_info_for_sessions(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
        )

        assert earliest_start is None
        assert record_count == 0

    async def test_counts_only_sessions_after_start_at(self, generate_sessions, make_batch_export):
        early_time = dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC)
        late_time = dt.datetime(2021, 1, 20, 0, 0, 0, tzinfo=dt.UTC)

        await generate_sessions(start_time=early_time, count=5)
        await generate_sessions(start_time=late_time, count=8)

        batch_export = make_batch_export()
        earliest_start, record_count = await _get_backfill_info_for_sessions(
            batch_export=batch_export,
            start_at=dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC),
            end_at=None,
        )

        assert earliest_start == dt.datetime(2021, 1, 20, 0, 0, 0, tzinfo=dt.UTC)
        assert record_count == 8

    async def test_counts_only_sessions_before_end_at(self, ateam, generate_sessions, make_batch_export):
        early_time = dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC)
        late_time = dt.datetime(2021, 1, 20, 0, 0, 0, tzinfo=dt.UTC)

        await generate_sessions(start_time=early_time, count=5)
        await generate_sessions(start_time=late_time, count=8)

        batch_export = make_batch_export()
        earliest_start, record_count = await _get_backfill_info_for_sessions(
            batch_export=batch_export,
            start_at=None,
            end_at=dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC),
        )

        assert earliest_start == dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC)
        assert record_count == 5

    @pytest.mark.parametrize(
        "interval,expected_start",
        [
            ("hour", dt.datetime(2021, 1, 15, 10, 0, 0, tzinfo=dt.UTC)),
            ("every 5 minutes", dt.datetime(2021, 1, 15, 10, 35, 0, tzinfo=dt.UTC)),
        ],
    )
    async def test_earliest_start_aligned_to_interval(
        self, interval, expected_start, generate_sessions, make_batch_export
    ):
        session_time = dt.datetime(2021, 1, 15, 10, 37, 45, tzinfo=dt.UTC)
        await generate_sessions(start_time=session_time, count=3)

        batch_export = make_batch_export(interval=interval)
        earliest_start, _ = await _get_backfill_info_for_sessions(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
        )
        assert earliest_start == expected_start
