from posthog.test.base import BaseTest

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.schema.error_tracking_fingerprint_issue_state import (
    ErrorTrackingFingerprintIssueStateTable,
)
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer.utils import prepare_and_print_ast


class TestErrorTrackingFingerprintIssueStateTable(BaseTest):
    def setUp(self):
        super().setUp()
        self.database = Database.create_for(team=self.team)
        self.context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, database=self.database)

    def _print_clickhouse(self, query: str) -> str:
        out = prepare_and_print_ast(parse_select(query), self.context, dialect="clickhouse")
        return out[0] if isinstance(out, tuple) else out

    def test_resolves_under_posthog_namespace(self):
        table = self.database.get_table(["posthog", "error_tracking_fingerprint_issue_state"])
        assert isinstance(table, ErrorTrackingFingerprintIssueStateTable)
        assert table.to_printed_hogql() == "error_tracking_fingerprint_issue_state"

    def test_not_registered_at_root(self):
        with self.assertRaises(QueryError):
            self.database.get_table(["error_tracking_fingerprint_issue_state"])

    def test_unaliased_namespaced_select_compiles(self):
        # Regression: `FROM posthog.error_tracking_fingerprint_issue_state` without an alias
        # used to raise KeyError because the LazyTable was registered under the joined alias
        # `posthog__error_tracking_fingerprint_issue_state` while `get_long_table_name` returned
        # the short name. The wrap in `TableAliasType` is what keeps them in sync.
        sql = self._print_clickhouse(
            "SELECT issue_status, count() AS issues "
            "FROM posthog.error_tracking_fingerprint_issue_state "
            "GROUP BY issue_status"
        )
        assert "error_tracking_fingerprint_issue_state" in sql

    def test_unaliased_namespaced_select_with_filter_compiles(self):
        sql = self._print_clickhouse(
            "SELECT fingerprint, issue_id "
            "FROM posthog.error_tracking_fingerprint_issue_state "
            "WHERE issue_status = 'active' LIMIT 5"
        )
        assert "error_tracking_fingerprint_issue_state" in sql

    def test_aliased_namespaced_select_compiles(self):
        # User-provided alias should keep working.
        sql = self._print_clickhouse(
            "SELECT s.issue_status FROM posthog.error_tracking_fingerprint_issue_state AS s LIMIT 1"
        )
        assert "error_tracking_fingerprint_issue_state" in sql
