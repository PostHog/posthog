from datetime import UTC, datetime

from freezegun import freeze_time
from posthog.test.base import APIBaseTest

from posthog.schema import DateRange

from posthog.session_recordings.queries.sub_queries.base_query import SessionRecordingsQueryDateRange


@freeze_time("2021-01-01T13:46:23")
class TestSessionRecordingsQueryDateRange(APIBaseTest):
    def test_with_relative_dates(self) -> None:
        query_date_range = SessionRecordingsQueryDateRange(
            date_range=DateRange(date_from="-3d", date_to="-24h", explicitDate=True),
            team=self.team,
            interval=None,
            now=datetime.now(UTC),
        )

        assert query_date_range.date_from() == datetime(2020, 12, 29, 0, 0, 0, 0, UTC)
        assert query_date_range.date_to() == datetime(
            year=2020, month=12, day=31, hour=13, minute=46, second=23, tzinfo=UTC
        )

    def test_with_string_dates(self) -> None:
        query_date_range = SessionRecordingsQueryDateRange(
            date_range=DateRange(date_from="2020-12-29", date_to="2021-01-01", explicitDate=True),
            team=self.team,
            interval=None,
            now=datetime.now(UTC),
        )

        assert query_date_range.date_from() == datetime(2020, 12, 29, 0, 0, 0, 0, UTC)
        assert query_date_range.date_to() == datetime(
            year=2021, month=1, day=1, hour=23, minute=59, second=59, microsecond=999999, tzinfo=UTC
        )

    def test_with_string_date_times(self) -> None:
        query_date_range = SessionRecordingsQueryDateRange(
            date_range=DateRange(date_from="2020-12-29T12:23:45Z", date_to="2021-01-01T13:34:42Z", explicitDate=True),
            team=self.team,
            interval=None,
            now=datetime.now(UTC),
        )

        assert query_date_range.date_from() == datetime(2020, 12, 29, 12, 23, 45, tzinfo=UTC)
        assert query_date_range.date_to() == datetime(
            year=2021, month=1, day=1, hour=13, minute=34, second=42, tzinfo=UTC
        )

    def test_with_no_date_from(self) -> None:
        query_date_range = SessionRecordingsQueryDateRange(
            date_range=DateRange(date_from=None, date_to="2021-01-01T13:34:42Z", explicitDate=True),
            team=self.team,
            interval=None,
            now=datetime.now(UTC),
        )

        # defaults to start of 7 days ago
        assert query_date_range.date_from() == datetime(2020, 12, 25, 0, 0, 0, 0, UTC)
        assert query_date_range.date_to() == datetime(
            year=2021, month=1, day=1, hour=13, minute=34, second=42, tzinfo=UTC
        )

    def test_with_no_date_to(self) -> None:
        query_date_range = SessionRecordingsQueryDateRange(
            date_range=DateRange(date_from="2021-01-01T11:34:42Z", date_to=None, explicitDate=True),
            team=self.team,
            interval=None,
            now=datetime.now(UTC),
        )

        assert query_date_range.date_from() == datetime(2021, 1, 1, 11, 34, 42, tzinfo=UTC)
        # defaults to now
        assert query_date_range.date_to() == datetime(
            year=2021, month=1, day=1, hour=13, minute=46, second=23, tzinfo=UTC
        )
