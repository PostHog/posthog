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

MARKERS = {"deep": "deep", "fast": "fast", "other": "other", 7: "seven", "2026-01-01": "date"}


class _MarkerOrder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.markers: list[str] = []

    def visit_constant(self, node: ast.Constant) -> None:
        for value in node.value if isinstance(node.value, list) else [node.value]:
            if value is True:
                self.markers.append("true")
            elif isinstance(value, (str, int)) and not isinstance(value, bool) and value in MARKERS:
                self.markers.append(MARKERS[value])

    def visit_json_subcolumn_access(self, node: ast.JsonSubcolumnAccess) -> None:
        if node.keys[0] in MARKERS:
            self.markers.append(MARKERS[node.keys[0]])


class TestFastPropertyFiltersFirst(SimpleTestCase):
    def _filter_order(
        self,
        where: str,
        *,
        native: bool = True,
        table: str = "events",
        property_types: dict[str, str] | None = None,
        placeholders: dict[str, ast.Expr] | None = None,
    ) -> list[str]:
        metadata = PropertyMetadata(
            event_properties={name: {"type": property_type} for name, property_type in (property_types or {}).items()}
        )
        context = HogQLContext(
            use_new_events_schema=native,
            property_metadata=metadata,
            database=Database(),
            apply_events_retention_floor=False,
        )
        context.property_swapper = PropertySwapper("UTC", metadata.event_properties, {}, {}, context, False)
        prepared = prepare_ast_for_printing(
            parse_select(f"SELECT count() FROM {table} WHERE {where}", placeholders), context, "clickhouse"
        )
        assert isinstance(prepared, ast.SelectQuery)
        assert prepared.where is not None
        order = _MarkerOrder()
        order.visit(prepared.where)
        return order.markers

    @parameterized.expand(
        [
            (
                "fast_filter_moves_to_the_front",
                "event = 'other' AND properties.query.kind = 'deep' AND properties.query_type = 'fast'",
                ["fast", "other", "deep"],
            ),
            (
                "conversion_stays_behind_the_filter_that_guards_it",
                "properties.query.kind = 'deep' AND event::int > 7 AND properties.query_type = 'fast'",
                ["fast", "deep", "seven"],
            ),
            (
                "property_filter_that_can_throw_stays",
                "properties.query.kind = 'deep' AND properties.plan::int > 7",
                ["deep", "seven"],
            ),
            (
                "comparison_with_another_column_stays",
                "properties.query.kind = 'deep' AND properties.plan = concat('fast', event)",
                ["deep", "fast"],
            ),
            (
                "negated_comparison_stays",
                "properties.query.kind = 'deep' AND properties.query_type != 'fast'",
                ["deep", "fast"],
            ),
            (
                "test_that_a_property_is_set_moves",
                "properties.query.kind = 'deep' AND properties.fast IS NOT NULL",
                ["fast", "deep"],
            ),
            (
                "whole_feature_flag_map_stays",
                "properties.query.kind = 'deep' AND properties.$feature_flags = 'fast'",
                ["deep", "fast"],
            ),
            (
                "active_feature_flags_stay",
                "properties.query.kind = 'deep' AND properties.$active_feature_flags = 'fast'",
                ["deep", "fast"],
            ),
            (
                "one_feature_flag_stays",
                "properties.query.kind = 'deep' AND properties.`$feature/beta` = 'fast'",
                ["deep", "fast"],
            ),
            (
                "nothing_moves_ahead_of_a_function_that_numbers_the_rows_it_is_given",
                "rowNumberInBlock() = length(properties.plan) - 7 AND properties.query_type = 'fast'",
                ["seven", "fast"],
            ),
        ]
    )
    def test_filter_order_on_the_native_table(self, _name: str, where: str, expected: list[str]) -> None:
        assert self._filter_order(where) == expected

    def test_a_conversion_with_an_argument_that_can_throw_stays(self) -> None:
        order = self._filter_order(
            "properties.query.kind = 'deep' AND transform(properties.plan, {keys}, {values}, event::int) > 7",
            placeholders={"keys": ast.Constant(value=["fast"]), "values": ast.Constant(value=[1])},
        )
        assert order == ["deep", "fast", "seven"]

    def test_a_list_passed_as_one_constant_moves(self) -> None:
        order = self._filter_order(
            "properties.query.kind = 'deep' AND properties.query_type IN {values}",
            placeholders={"values": ast.Constant(value=["fast"])},
        )
        assert order == ["fast", "deep"]

    @parameterized.expand(
        [
            ("number", "properties.duration > 7", ["seven", "deep"]),
            ("boolean", "properties.active = true", ["true", "deep"]),
            ("date", "properties.signed_up > '2026-01-01'", ["date", "deep"]),
        ]
    )
    def test_a_comparison_of_a_typed_property_is_fast(self, _name: str, comparison: str, expected: list[str]) -> None:
        order = self._filter_order(
            f"properties.query.kind = 'deep' AND {comparison}",
            property_types={"duration": "Numeric", "active": "Boolean", "signed_up": "DateTime"},
        )
        assert order == expected

    @parameterized.expand(
        [
            ("legacy_events_table", False, "events"),
            ("text_properties_on_another_table", True, "posthog.ai_events"),
        ]
    )
    def test_a_property_outside_a_native_json_column_keeps_the_written_order(
        self, _name: str, native: bool, table: str
    ) -> None:
        order = self._filter_order(
            "properties.query.kind = 'deep' AND properties.query_type = 'fast'", native=native, table=table
        )
        assert order == ["deep", "fast"]
