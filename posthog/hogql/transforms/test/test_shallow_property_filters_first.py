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

MARKERS = {"deep": "deep", "%deep%": "deep", "shallow": "shallow", "other": "other", 7: "seven"}


class _MarkerOrder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.markers: list[str] = []

    def visit_constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, (str, int)) and not isinstance(node.value, bool) and node.value in MARKERS:
            self.markers.append(MARKERS[node.value])


class TestShallowPropertyFiltersFirst(SimpleTestCase):
    def _filter_order(
        self,
        where: str,
        *,
        native: bool = True,
        from_clause: str = "events",
        numeric_properties: tuple[str, ...] = (),
    ) -> list[str]:
        metadata = PropertyMetadata(event_properties={name: {"type": "Numeric"} for name in numeric_properties})
        context = HogQLContext(
            use_new_events_schema=native,
            property_metadata=metadata,
            database=Database(),
            apply_events_retention_floor=False,
        )
        context.property_swapper = PropertySwapper("UTC", metadata.event_properties, {}, {}, context, False)
        prepared = prepare_ast_for_printing(
            parse_select(f"SELECT count() FROM {from_clause} WHERE {where}"), context, "clickhouse"
        )
        assert isinstance(prepared, ast.SelectQuery)
        assert prepared.where is not None
        order = _MarkerOrder()
        order.visit(prepared.where)
        return order.markers

    @parameterized.expand(
        [
            (
                "path_below_the_first_level",
                "properties.query.source.accountId = 'deep' AND event = 'other' AND properties.query_type = 'shallow'",
                ["shallow", "deep", "other"],
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
            (
                "conversion_stays_behind_the_filter_that_guards_it",
                "properties.query.kind = 'deep' AND event::int > 7 AND properties.query_type = 'shallow'",
                ["shallow", "deep", "seven"],
            ),
        ]
    )
    def test_moves_a_shallow_comparison_in_front_of_a_deep_filter_on_the_same_column(
        self, _name: str, where: str, expected: list[str]
    ) -> None:
        assert self._filter_order(where) == expected

    def test_moves_a_comparison_of_a_typed_property(self) -> None:
        order = self._filter_order(
            "properties.query.kind = 'deep' AND properties.duration > 7", numeric_properties=("duration",)
        )
        assert order == ["seven", "deep"]

    @parameterized.expand(
        [
            ("only_a_top_level_column_follows", "properties.query.kind = 'deep' AND event = 'other'", True, "events"),
            (
                "shallow_filter_is_on_another_json_column",
                "properties.query.kind = 'deep' AND poe.properties.plan = 'shallow'",
                True,
                "events",
            ),
            (
                "shallow_filter_is_on_another_scan_of_events",
                "a.properties.query.kind = 'deep' AND b.properties.plan = 'shallow'",
                True,
                "events AS a JOIN events AS b ON a.distinct_id = b.distinct_id",
            ),
            (
                "shallow_filter_can_throw",
                "properties.query.kind = 'deep' AND properties.plan::int > 7",
                True,
                "events",
            ),
            (
                "deep_filter_belongs_to_a_subquery",
                "event IN (SELECT event FROM events WHERE properties.query.kind = 'deep') "
                "AND properties.query_type = 'shallow'",
                True,
                "events",
            ),
            (
                "legacy_events_table",
                "properties.query.kind = 'deep' AND properties.query_type = 'shallow'",
                False,
                "events",
            ),
        ]
    )
    def test_keeps_the_written_order_otherwise(self, _name: str, where: str, native: bool, from_clause: str) -> None:
        assert self._filter_order(where, native=native, from_clause=from_clause)[0] == "deep"
