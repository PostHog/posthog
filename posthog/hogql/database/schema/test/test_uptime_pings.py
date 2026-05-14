from posthog.test.base import BaseTest

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast


class TestUptimePingsTable(BaseTest):
    def _print(self, sql: str) -> str:
        db = Database.create_for(team=self.team)
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, database=db)
        query, _ = prepare_and_print_ast(parse_select(sql), context, dialect="clickhouse")
        return query

    def test_select_columns(self):
        query = self._print("SELECT monitor_id, timestamp, outcome, latency_ms, status_code FROM posthog.uptime_pings")
        assert "uptime_pings" in query
        assert "monitor_id" in query
        assert "outcome" in query

    def test_team_id_filter_is_injected(self):
        query = self._print("SELECT count() FROM posthog.uptime_pings")
        assert f"equals(uptime_pings.team_id, {self.team.pk})" in query

    def test_uptime_percentage_aggregation(self):
        query = self._print(
            """
            SELECT toDate(timestamp) AS day, countIf(outcome = 'success') / count() AS uptime
            FROM posthog.uptime_pings
            GROUP BY day
            """
        )
        assert "uptime_pings" in query
        assert f"equals(uptime_pings.team_id, {self.team.pk})" in query
