from typing import Any

import pytest
from posthog.test.base import BaseTest

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.transforms.order_by_pushdown import push_down_order_by


class TestOrderByPushdown(BaseTest):
    snapshot: Any
    maxDiff = None

    def _apply_pushdown(self, query: str) -> tuple[str, str]:
        parsed = parse_select(query)
        assert isinstance(parsed, ast.SelectQuery)
        before = parsed.to_hogql()

        assert parsed.select_from is not None
        inner = parsed.select_from.table
        assert isinstance(inner, ast.SelectQuery)

        push_down_order_by(
            outer_query=parsed,
            inner_query=inner,
            outer_table_alias="inner",
            inner_table_name="events",
            should_push_down=lambda order_expr, select_query: True,
        )

        after = parsed.to_hogql()
        return before, after

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_pushdown_simple_field(self):
        before, after = self._apply_pushdown(
            "SELECT team_id FROM (SELECT team_id FROM events) AS inner ORDER BY team_id LIMIT 10"
        )
        assert {"before": before, "after": after} == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_pushdown_inner_alias(self):
        before, after = self._apply_pushdown(
            "SELECT t_id FROM (SELECT team_id AS t_id FROM events) AS inner ORDER BY t_id LIMIT 10"
        )
        assert {"before": before, "after": after} == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_pushdown_outer_alias(self):
        before, after = self._apply_pushdown(
            "SELECT team_id AS t_id FROM (SELECT team_id FROM events) AS inner ORDER BY t_id LIMIT 10"
        )
        assert {"before": before, "after": after} == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_pushdown_qualified_reference(self):
        before, after = self._apply_pushdown(
            "SELECT inner.team_id FROM (SELECT team_id FROM events) AS inner ORDER BY inner.team_id LIMIT 10"
        )
        assert {"before": before, "after": after} == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_pushdown_function_call(self):
        before, after = self._apply_pushdown(
            "SELECT count(team_id) FROM (SELECT team_id FROM events) AS inner ORDER BY count(team_id) LIMIT 10"
        )
        assert {"before": before, "after": after} == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_no_pushdown_without_limit(self):
        before, after = self._apply_pushdown(
            "SELECT team_id FROM (SELECT team_id FROM events) AS inner ORDER BY team_id"
        )
        assert {"before": before, "after": after} == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_pushdown_preserves_existing_inner_order_by(self):
        before, after = self._apply_pushdown(
            "SELECT team_id FROM (SELECT team_id FROM events ORDER BY event) AS inner ORDER BY team_id LIMIT 10"
        )
        assert {"before": before, "after": after} == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_pushdown_qualified_inner_alias(self):
        before, after = self._apply_pushdown(
            "SELECT inner.t_id FROM (SELECT team_id AS t_id FROM events) AS inner ORDER BY inner.t_id LIMIT 10"
        )
        assert {"before": before, "after": after} == self.snapshot
