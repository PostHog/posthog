from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import (
    DatabaseField,
    DateTimeDatabaseField,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
)
from posthog.hogql.database.schema.session_replay_features import SessionReplayFeaturesTable
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer.utils import prepare_and_print_ast


class TestSessionReplayFeaturesTable(BaseTest):
    def setUp(self):
        super().setUp()
        self.database = Database.create_for(team=self.team)
        self.context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, database=self.database)

    def _print_clickhouse(self, query: str) -> str:
        out = prepare_and_print_ast(parse_select(query), self.context, dialect="clickhouse")
        return out[0] if isinstance(out, tuple) else out

    def test_resolves_under_posthog_namespace(self):
        table = self.database.get_table(["posthog", "session_replay_features"])
        assert isinstance(table, SessionReplayFeaturesTable)
        assert table.to_printed_clickhouse(self.context) == "session_replay_features"
        assert table.to_printed_hogql() == "session_replay_features"

    def test_not_registered_at_root(self):
        with self.assertRaises(QueryError):
            self.database.get_table(["session_replay_features"])

    @parameterized.expand(
        [
            ("session_id", StringDatabaseField),
            ("team_id", IntegerDatabaseField),
            ("distinct_id", StringDatabaseField),
            ("min_first_timestamp", DateTimeDatabaseField),
            ("max_last_timestamp", DateTimeDatabaseField),
            ("click_count", IntegerDatabaseField),
            ("rage_click_count", IntegerDatabaseField),
            ("mouse_distance_traveled", FloatDatabaseField),
            ("max_idle_gap_ms", FloatDatabaseField),
            ("is_deleted", IntegerDatabaseField),
        ]
    )
    def test_typed_field(self, name: str, expected_type: type):
        field = SessionReplayFeaturesTable.model_fields["fields"].default[name]
        assert isinstance(field, expected_type), f"{name} should be {expected_type.__name__}"

    @parameterized.expand([("unique_url_count",), ("unique_click_target_count",)])
    def test_uniq_exact_columns_are_opaque(self, name: str):
        # AggregateFunction(uniqExact, …) state. Exposed as plain DatabaseField so users must wrap with
        # uniqExactMerge to get a count. Anything stricter would prevent the merge call from typechecking.
        field = SessionReplayFeaturesTable.model_fields["fields"].default[name]
        assert type(field) is DatabaseField

    def test_simple_select_compiles(self):
        sql = self._print_clickhouse(
            "SELECT session_id, sum(click_count) AS clicks "
            "FROM posthog.session_replay_features "
            "WHERE team_id = 1 GROUP BY session_id LIMIT 5"
        )
        assert "FROM session_replay_features" in sql
        assert "sum(session_replay_features.click_count) AS clicks" in sql
        assert "GROUP BY session_replay_features.session_id" in sql

    def test_uniq_exact_merge_wraps_aggregate_state(self):
        sql = self._print_clickhouse(
            "SELECT session_id, "
            "uniqExactMerge(unique_url_count) AS unique_urls, "
            "uniqExactMerge(unique_click_target_count) AS unique_targets "
            "FROM posthog.session_replay_features "
            "WHERE team_id = 1 GROUP BY session_id LIMIT 5"
        )
        assert "uniqExactMerge(session_replay_features.unique_url_count) AS unique_urls" in sql
        assert "uniqExactMerge(session_replay_features.unique_click_target_count) AS unique_targets" in sql

    def test_max_last_timestamp_compiles(self):
        # SimpleAggregateFunction(max, DateTime64) should select like a plain DateTime, no -Merge required.
        sql = self._print_clickhouse(
            "SELECT max(max_last_timestamp) AS last_seen FROM posthog.session_replay_features WHERE team_id = 1 LIMIT 1"
        )
        assert "max(toTimeZone(session_replay_features.max_last_timestamp" in sql

    def test_resolvable_in_table_tree_under_posthog_namespace(self):
        names = self.database.tables.resolve_all_table_names()
        assert "posthog.session_replay_features" in names
