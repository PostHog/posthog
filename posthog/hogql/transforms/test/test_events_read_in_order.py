from typing import cast

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import resolve_types
from posthog.hogql.transforms.events_read_in_order import order_events_reads_by_sort_key


class TestEventsReadInOrder(BaseTest):
    def _resolved(self, query: str) -> ast.SelectQuery:
        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
        context.database = Database.create_for(context.team_id, modifiers=context.modifiers, team=context.team)
        return cast(ast.SelectQuery, resolve_types(parse_select(query), context, dialect="clickhouse"))

    def test_prefixes_once_with_the_same_direction(self):
        node = self._resolved("SELECT event FROM events ORDER BY timestamp DESC LIMIT 10")
        assert node.order_by is not None
        original_key = node.order_by[0]

        order_events_reads_by_sort_key(node)
        order_events_reads_by_sort_key(node)

        prefix, key = node.order_by
        assert key is original_key
        assert prefix.order == "DESC"
        assert isinstance(prefix.expr, ast.Call)
        assert prefix.expr.name == "_toDate"
        assert isinstance(prefix.expr.args[0], ast.Field)
        assert prefix.expr.args[0].chain == ["timestamp"]

    @parameterized.expand(
        [
            ("no_limit", "SELECT event FROM events ORDER BY timestamp DESC"),
            ("other_first_key", "SELECT event FROM events ORDER BY event, timestamp LIMIT 10"),
            (
                "select_alias_named_timestamp",
                "SELECT toStartOfDay(timestamp) AS timestamp FROM events ORDER BY timestamp LIMIT 10",
            ),
            ("other_table_timestamp_column", "SELECT timestamp FROM heatmaps ORDER BY timestamp DESC LIMIT 10"),
            ("persons_created_at", "SELECT id FROM persons ORDER BY created_at DESC LIMIT 10"),
            ("with_fill", "SELECT event FROM events ORDER BY timestamp WITH FILL LIMIT 10"),
        ]
    )
    def test_leaves_other_order_bys_alone(self, _name: str, query: str):
        node = self._resolved(query)
        assert node.order_by is not None
        keys_before = [id(key) for key in node.order_by]

        order_events_reads_by_sort_key(node)

        assert [id(key) for key in node.order_by] == keys_before

    def test_leaves_window_order_by_alone(self):
        node = self._resolved("SELECT event, row_number() OVER (ORDER BY timestamp DESC) AS n FROM events LIMIT 10")
        window = node.select[1]
        assert isinstance(window, ast.Alias)
        assert isinstance(window.expr, ast.WindowFunction)
        assert window.expr.over_expr is not None
        assert window.expr.over_expr.order_by is not None
        keys_before = [id(key) for key in window.expr.over_expr.order_by]

        order_events_reads_by_sort_key(node)

        assert [id(key) for key in window.expr.over_expr.order_by] == keys_before
