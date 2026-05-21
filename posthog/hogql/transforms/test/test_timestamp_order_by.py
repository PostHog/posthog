import re
from datetime import datetime

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import execute_hogql_query


def _normalize(sql: str) -> str:
    # toTimeZone gets a parameterized timezone constant; collapse it for stable assertions.
    return re.sub(r"%\(hogql_val_\d+\)s", "hogval", sql)


class TestTimestampOrderByRewrite(ClickhouseTestMixin, BaseTest):
    def _print(self, select: str, timezone: str = "UTC") -> str:
        if self.team.timezone != timezone:
            self.team.timezone = timezone
            self.team.save()
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        sql, _ = prepare_and_print_ast(parse_select(select), context, "clickhouse")
        return _normalize(sql)

    @parameterized.expand(["ASC", "DESC"])
    def test_leading_timestamp_with_limit_is_rewritten(self, direction: str):
        sql = self._print(f"SELECT uuid FROM events ORDER BY timestamp {direction} LIMIT 100")
        assert f"ORDER BY toDate(events.timestamp) {direction}, events.timestamp {direction}" in sql
        # The toDate argument must be the bare field — toDate(toTimeZone(...)) is the
        # project-local date and would not match the UTC toDate(timestamp) sort key.
        assert "toDate(toTimeZone(" not in sql
        # The leading order term is no longer the (unprunable) toTimeZone form.
        assert f"ORDER BY toTimeZone(events.timestamp, hogval) {direction}" not in sql
        # Buffering off so the LIMIT early-terminates instead of over-reading.
        assert "read_in_order_use_buffering=0" in sql

    def test_rewrite_keeps_trailing_order_terms(self):
        sql = self._print("SELECT uuid FROM events ORDER BY timestamp DESC, event ASC LIMIT 10")
        assert "ORDER BY toDate(events.timestamp) DESC, events.timestamp DESC, events.event ASC" in sql

    def test_rewrite_applies_inside_subquery(self):
        sql = self._print(
            "SELECT e.uuid FROM (SELECT uuid, timestamp FROM events ORDER BY timestamp DESC LIMIT 100) AS e"
        )
        assert "ORDER BY toDate(events.timestamp) DESC, events.timestamp DESC" in sql

    def test_select_projection_keeps_project_timezone(self):
        sql = self._print("SELECT timestamp FROM events ORDER BY timestamp DESC LIMIT 10", timezone="America/New_York")
        # SELECT still converts the displayed value to the project timezone ...
        assert "SELECT toTimeZone(events.timestamp, hogval)" in sql
        # ... but ORDER BY leads with the bare, key-aligned toDate(timestamp).
        assert "ORDER BY toDate(events.timestamp) DESC, events.timestamp DESC" in sql

    def test_rewrite_composes_with_where_range_pruning(self):
        sql = self._print(
            "SELECT distinct_id FROM events WHERE timestamp > '2024-02-11' ORDER BY timestamp ASC LIMIT 5",
            timezone="US/Pacific",
        )
        # WHERE keeps the bare timestamp (so the partition/PK can prune the range) ...
        assert "greater(events.timestamp" in sql
        assert "greater(toTimeZone(events.timestamp" not in sql
        # ... and ORDER BY leads with the key-aligned toDate(timestamp).
        assert "ORDER BY toDate(events.timestamp) ASC, events.timestamp ASC" in sql

    def test_no_limit_not_rewritten(self):
        sql = self._print("SELECT uuid FROM events ORDER BY timestamp DESC")
        assert "toDate(events.timestamp)" not in sql
        assert "ORDER BY toTimeZone(events.timestamp, hogval) DESC" in sql
        # No rewrite means the buffering setting is not added either.
        assert "read_in_order_use_buffering" not in sql

    def test_group_by_not_rewritten(self):
        sql = self._print("SELECT timestamp, count() FROM events GROUP BY timestamp ORDER BY timestamp DESC LIMIT 10")
        assert "toDate(events.timestamp)" not in sql

    def test_non_leading_timestamp_not_rewritten(self):
        sql = self._print("SELECT uuid FROM events ORDER BY event ASC, timestamp DESC LIMIT 10")
        assert "toDate(events.timestamp)" not in sql

    def test_function_wrapped_timestamp_not_rewritten(self):
        sql = self._print("SELECT uuid FROM events ORDER BY toStartOfHour(timestamp) DESC LIMIT 10")
        assert "toDate(events.timestamp)" not in sql
        assert "ORDER BY toStartOfHour(" in sql

    def test_created_at_not_rewritten(self):
        sql = self._print("SELECT uuid FROM events ORDER BY created_at DESC LIMIT 10")
        assert "toDate(events.timestamp)" not in sql
        assert "toDate(events.created_at)" not in sql

    def test_subquery_alias_column_not_rewritten(self):
        # Ordering by a subquery-projected column is not the events base-table timestamp,
        # so the leading term must not be rewritten.
        sql = self._print("SELECT t.ts FROM (SELECT timestamp AS ts FROM events) AS t ORDER BY ts DESC LIMIT 10")
        assert "ORDER BY toDate(" not in sql


class TestTimestampOrderByCorrectness(ClickhouseTestMixin, BaseTest):
    # February 2024 keeps US/Pacific at a fixed UTC-8 (no DST transition), so the
    # UTC-vs-local date split around midnight is unambiguous. Stored as UTC instants.
    INSTANTS = [
        ("u0", datetime(2024, 2, 10, 23, 0)),  # UTC 02-10, Pacific 02-10 15:00
        ("u1", datetime(2024, 2, 11, 2, 0)),  # UTC 02-11, Pacific 02-10 18:00 (same Pacific day as u0)
        ("u2", datetime(2024, 2, 11, 9, 0)),  # UTC 02-11, Pacific 02-11 01:00
        ("u3", datetime(2024, 2, 12, 20, 0)),
        ("u4", datetime(2024, 2, 12, 21, 30)),  # same UTC day as u3 (within-day tiebreaker)
    ]

    def setUp(self):
        super().setUp()
        self.team.timezone = "US/Pacific"
        self.team.save()
        for distinct_id, ts in self.INSTANTS:
            _create_event(team=self.team, distinct_id=distinct_id, event="$pageview", timestamp=ts)
        flush_persons_and_events()

    def _order(self, direction: str, limit: int) -> tuple[list[str], str]:
        response = execute_hogql_query(
            f"SELECT distinct_id FROM events ORDER BY timestamp {direction} LIMIT {limit}", team=self.team
        )
        assert response.results is not None
        # response.clickhouse is pretty-printed (newlines/indentation); collapse whitespace.
        return [row[0] for row in response.results], re.sub(r"\s+", " ", response.clickhouse or "")

    def test_ascending_matches_instant_order(self):
        got, sql = self._order("ASC", 3)
        assert "ORDER BY toDate(events.timestamp) ASC, events.timestamp ASC" in sql
        assert got == ["u0", "u1", "u2"]

    def test_descending_matches_instant_order(self):
        got, sql = self._order("DESC", 3)
        assert "ORDER BY toDate(events.timestamp) DESC, events.timestamp DESC" in sql
        assert got == ["u4", "u3", "u2"]

    def test_ascending_is_reverse_of_descending(self):
        asc, _ = self._order("ASC", 5)
        desc, _ = self._order("DESC", 5)
        assert asc == list(reversed(desc))
        assert asc == ["u0", "u1", "u2", "u3", "u4"]
