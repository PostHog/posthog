from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.hogql.query import HogQLQueryExecutor
from posthog.hogql.team_first_prewhere import should_check_team_first_in_prewhere

from posthog.clickhouse.workload import Workload
from posthog.models.team.team_event_volume import TeamEventVolume

FLAG_CHECK = "posthog.hogql.team_first_prewhere.feature_enabled_or_false"
VOLUME_READ = "posthog.hogql.team_first_prewhere._recent_events_last_year"
ERROR_REPORT = "posthog.hogql.team_first_prewhere.capture_exception"


class TestShouldCheckTeamFirstInPrewhere(BaseTest):
    def _add_volume(self, events_last_year: int, age: timedelta = timedelta()) -> None:
        TeamEventVolume.objects.unscoped().create(
            team=self.team, events_last_year=events_last_year, computed_at=timezone.now() - age
        )

    @parameterized.expand(
        [
            ("small_team", True, 99_999_999, timedelta(), True),
            ("team_at_the_boundary", True, 100_000_000, timedelta(), False),
            ("team_without_a_volume_row", True, None, timedelta(), False),
            ("volume_just_within_max_age", True, 1, timedelta(days=2), True),
            ("volume_older_than_max_age", True, 1, timedelta(days=4), False),
            ("flag_off", False, 1, timedelta(), False),
        ]
    )
    def test_applies_only_to_small_flagged_teams_with_a_recent_volume(
        self, _name: str, flag: bool, events_last_year: int | None, age: timedelta, expected: bool
    ) -> None:
        if events_last_year is not None:
            self._add_volume(events_last_year, age)

        with patch(FLAG_CHECK, return_value=flag), patch(ERROR_REPORT) as report:
            assert should_check_team_first_in_prewhere(self.team, Workload.DEFAULT) is expected

        report.assert_not_called()

    @parameterized.expand([("flag_check", FLAG_CHECK), ("volume_read", VOLUME_READ)])
    def test_error_turns_the_setting_off_and_is_reported(self, _name: str, failing_call: str) -> None:
        self._add_volume(1)

        with patch(FLAG_CHECK, return_value=True), patch(ERROR_REPORT) as report:
            with patch(failing_call, side_effect=RuntimeError("unavailable")):
                assert should_check_team_first_in_prewhere(self.team, Workload.DEFAULT) is False

        report.assert_called_once()

    @parameterized.expand(
        [
            ("events", "SELECT count() FROM events", True),
            ("logs", "SELECT count() FROM logs", False),
        ]
    )
    def test_compiled_sql_carries_the_setting_for_events_but_not_logs(
        self, _name: str, query: str, expected: bool
    ) -> None:
        self._add_volume(1)

        with patch(FLAG_CHECK, return_value=True):
            sql, _ = HogQLQueryExecutor(query=query, team=self.team, query_type="HogQLQuery").generate_clickhouse_sql()

        assert ("move_primary_key_columns_to_end_of_prewhere=0" in sql) is expected
