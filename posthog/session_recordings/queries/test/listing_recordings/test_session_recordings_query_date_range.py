from datetime import UTC, datetime

from freezegun import freeze_time
from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.schema import DateRange

from posthog.session_recordings.queries.sub_queries.base_query import SessionRecordingsQueryDateRange


@freeze_time("2021-01-01T13:46:23")
class TestSessionRecordingsQueryDateRange(APIBaseTest):
    @parameterized.expand(
        [
            (
                "relative_dates",
                "-3d",
                "-24h",
                datetime(2020, 12, 29, 0, 0, 0, 0, UTC),
                datetime(2020, 12, 31, 13, 46, 23, tzinfo=UTC),
            ),
            (
                "date_only_strings_get_start_and_end_of_day",
                "2020-12-29",
                "2021-01-01",
                datetime(2020, 12, 29, 0, 0, 0, 0, UTC),
                datetime(2021, 1, 1, 23, 59, 59, 999999, UTC),
            ),
            (
                "datetime_strings_preserve_exact_time",
                "2020-12-29T12:23:45Z",
                "2021-01-01T13:34:42Z",
                datetime(2020, 12, 29, 12, 23, 45, tzinfo=UTC),
                datetime(2021, 1, 1, 13, 34, 42, tzinfo=UTC),
            ),
            (
                "missing_date_from_defaults_to_7_days_ago",
                None,
                "2021-01-01T13:34:42Z",
                datetime(2020, 12, 25, 0, 0, 0, 0, UTC),
                datetime(2021, 1, 1, 13, 34, 42, tzinfo=UTC),
            ),
            (
                "missing_date_to_defaults_to_now",
                "2021-01-01T11:34:42Z",
                None,
                datetime(2021, 1, 1, 11, 34, 42, tzinfo=UTC),
                datetime(2021, 1, 1, 13, 46, 23, tzinfo=UTC),
            ),
        ]
    )
    def test_date_range_parsing(
        self,
        _name: str,
        input_date_from: str | None,
        input_date_to: str | None,
        expected_date_from: datetime,
        expected_date_to: datetime,
    ) -> None:
        query_date_range = SessionRecordingsQueryDateRange(
            date_range=DateRange(date_from=input_date_from, date_to=input_date_to, explicitDate=True),
            team=self.team,
            interval=None,
            now=datetime.now(UTC),
        )

        assert query_date_range.date_from() == expected_date_from
        assert query_date_range.date_to() == expected_date_to
