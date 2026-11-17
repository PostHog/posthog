from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer.utils import prepare_ast_for_printing
from posthog.hogql.query import HogQLQueryExecutor, execute_hogql_query
from posthog.hogql.team_first_prewhere import _events_last_year_cache, should_check_team_first_in_prewhere

from posthog.models.team.team_event_volume import TeamEventVolume

FLAG_CHECK = "posthog.hogql.team_first_prewhere.feature_enabled_or_false"
VOLUME_READ = "posthog.hogql.team_first_prewhere._recent_events_last_year"
ERROR_REPORT = "posthog.hogql.team_first_prewhere.capture_exception"


class TestShouldCheckTeamFirstInPrewhere(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        _events_last_year_cache.clear()

    def _add_volume(self, events_last_year: int, age: timedelta = timedelta()) -> None:
        TeamEventVolume.objects.unscoped().create(
            team=self.team, events_last_year=events_last_year, computed_at=timezone.now() - age
        )

    def _prepared_events_query(self) -> ast.AST | None:
        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
        return prepare_ast_for_printing(
            parse_select("SELECT count() FROM events"), context=context, dialect="clickhouse"
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
            assert should_check_team_first_in_prewhere(self.team, self._prepared_events_query()) is expected

        report.assert_not_called()

    @parameterized.expand([("flag_check", FLAG_CHECK), ("volume_read", VOLUME_READ)])
    def test_error_turns_the_setting_off_and_is_reported(self, _name: str, failing_call: str) -> None:
        self._add_volume(1)

        with patch(FLAG_CHECK, return_value=True), patch(ERROR_REPORT) as report:
            with patch(failing_call, side_effect=RuntimeError("unavailable")):
                assert should_check_team_first_in_prewhere(self.team, self._prepared_events_query()) is False

        report.assert_called_once()

    @parameterized.expand(
        [
            ("events", "SELECT count() FROM events", True),
            ("events_in_a_subquery", "SELECT count() FROM (SELECT event FROM events)", True),
            ("events_in_a_cte", "WITH e AS (SELECT event FROM events) SELECT count() FROM e", True),
            (
                "events_joined_to_persons",
                "SELECT count() FROM persons JOIN events ON persons.id = events.person_id",
                True,
            ),
            ("events_through_a_lazy_join", "SELECT events.event FROM session_replay_events", True),
            ("persons", "SELECT count() FROM persons", False),
            ("session_replay_events", "SELECT count() FROM session_replay_events", False),
            ("logs", "SELECT count() FROM logs", False),
        ]
    )
    def test_compiled_sql_carries_the_setting_only_when_the_query_reads_events(
        self, _name: str, query: str, expected: bool
    ) -> None:
        self._add_volume(1)

        with patch(FLAG_CHECK, return_value=True):
            sql, _ = HogQLQueryExecutor(query=query, team=self.team, query_type="HogQLQuery").generate_clickhouse_sql()

        assert ("move_primary_key_columns_to_end_of_prewhere=0" in sql) is expected

    @parameterized.expand([("flag_on", True), ("flag_off", False)])
    def test_query_settings_without_the_field_run_without_the_setting(self, _name: str, flag: bool) -> None:
        self._add_volume(1)

        with (
            patch(FLAG_CHECK, return_value=flag),
            patch("posthog.hogql.query.sync_execute", return_value=([], [])) as clickhouse,
        ):
            execute_hogql_query(
                query="SELECT count() FROM events",
                team=self.team,
                query_type="HogQLQuery",
                settings=HogQLQuerySettings(),
            )

        assert "move_primary_key_columns_to_end_of_prewhere" not in clickhouse.call_args.args[0]
