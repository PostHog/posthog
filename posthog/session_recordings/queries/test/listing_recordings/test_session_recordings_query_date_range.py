from datetime import UTC, datetime

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import DateRange, HogQLQueryModifiers, RecordingsQuery, SessionTableVersion

from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery
from posthog.session_recordings.queries.sub_queries.base_query import SessionRecordingsQueryDateRange


@time_machine.travel("2021-01-01T13:46:23", tick=False)
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


@time_machine.travel("2026-11-13T12:00:00", tick=False)
class TestReplaySessionsTableVersion(APIBaseTest):
    @parameterized.expand(
        [
            ("recent_range_in_a_covered_region", "-7d", "US", None, None, SessionTableVersion.V3),
            ("last_30_days_in_a_covered_region", "-30d", "US", None, None, SessionTableVersion.V3),
            ("range_longer_than_30_days", "-60d", "US", None, None, None),
            ("range_before_the_coverage_start", "2026-09-25", "US", None, None, None),
            ("region_without_coverage", "-7d", "EU", None, None, None),
            ("team_pins_v2", "-7d", "US", "v2", None, None),
            ("request_pins_v2", "-7d", "US", None, SessionTableVersion.V2, SessionTableVersion.V2),
        ]
    )
    def test_recent_ranges_read_sessions_v3(
        self, _name, date_from, region, team_version, requested_version, expected_version
    ) -> None:
        if team_version:
            self.team.modifiers = {"sessionTableVersion": team_version}
            self.team.save()
        query = SessionRecordingListFromQuery(
            team=self.team,
            query=RecordingsQuery(date_from=date_from),
            hogql_query_modifiers=HogQLQueryModifiers(sessionTableVersion=requested_version)
            if requested_version
            else None,
        )

        with (
            patch("posthog.session_recordings.queries.session_recording_list_from_query.is_cloud", return_value=True),
            override_settings(CLOUD_DEPLOYMENT=region),
        ):
            modifiers = query._execution_modifiers

        assert (modifiers.sessionTableVersion if modifiers else None) == expected_version
