from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.printer.utils import prepare_ast_for_printing
from posthog.hogql.property_metadata import PropertyMetadata
from posthog.hogql.transforms.property_types import PropertySwapper
from posthog.hogql.visitor import TraversingVisitor

MARKERS = ("deep", "shallow", "other")


class _MarkerOrder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.markers: list[str] = []

    def visit_constant(self, node: ast.Constant) -> None:
        self.markers.extend(marker for marker in MARKERS if marker in str(node.value).split("%"))


class TestShallowPropertyFiltersFirst(SimpleTestCase):
    def _filter_order(self, where: str, *, native: bool = True) -> list[str]:
        context = HogQLContext(
            use_new_events_schema=native,
            property_metadata=PropertyMetadata(),
            database=Database(),
            apply_events_retention_floor=False,
        )
        context.property_swapper = PropertySwapper("UTC", {}, {}, {}, context, False)
        prepared = prepare_ast_for_printing(
            parse_select(f"SELECT count() FROM events WHERE {where}"), context, "clickhouse"
        )
        assert isinstance(prepared, ast.SelectQuery)
        order = _MarkerOrder()
        order.visit(prepared.where)
        return order.markers

    @parameterized.expand(
        [
            (
                "path_below_the_first_level",
                "properties.query.source.accountId = 'deep' AND event = 'other' AND properties.query_type = 'shallow'",
                ["other", "shallow", "deep"],
            ),
            (
                "json_function_over_a_property",
                "JSONType(properties.query) = 'deep' AND properties.query_type = 'shallow'",
                ["shallow", "deep"],
            ),
            (
                "whole_document",
                "toString(properties) LIKE '%deep%' AND properties.query_type = 'shallow'",
                ["shallow", "deep"],
            ),
            (
                "deep_leaf_inside_an_or",
                "(properties.query.kind = 'deep' OR event = 'other') AND properties.query_type = 'shallow'",
                ["shallow", "deep", "other"],
            ),
        ]
    )
    def test_moves_a_deep_filter_after_a_shallow_filter_on_the_same_column(
        self, _name: str, where: str, expected: list[str]
    ) -> None:
        assert self._filter_order(where) == expected

    @parameterized.expand(
        [
            ("only_a_top_level_column_follows", "properties.query.kind = 'deep' AND event = 'other'", True),
            (
                "shallow_filter_is_on_another_json_column",
                "properties.query.kind = 'deep' AND poe.properties.plan = 'shallow'",
                True,
            ),
            (
                "deep_filter_belongs_to_a_subquery",
                "event IN (SELECT event FROM events WHERE properties.query.kind = 'deep') "
                "AND properties.query_type = 'shallow'",
                True,
            ),
            ("legacy_events_table", "properties.query.kind = 'deep' AND properties.query_type = 'shallow'", False),
        ]
    )
    def test_keeps_the_written_order_otherwise(self, _name: str, where: str, native: bool) -> None:
        assert self._filter_order(where, native=native)[0] == "deep"
