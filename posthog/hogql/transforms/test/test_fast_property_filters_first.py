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

MARKERS = {"deep": "deep", "fast": "fast", "other": "other", 7: "seven"}


class _MarkerOrder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.markers: list[str] = []

    def visit_constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, (str, int)) and not isinstance(node.value, bool) and node.value in MARKERS:
            self.markers.append(MARKERS[node.value])


class TestFastPropertyFiltersFirst(SimpleTestCase):
    def _filter_order(
        self, where: str, *, native: bool = True, table: str = "events", numeric_properties: tuple[str, ...] = ()
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
            parse_select(f"SELECT count() FROM {table} WHERE {where}"), context, "clickhouse"
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
        ]
    )
    def test_filter_order_on_the_native_table(self, _name: str, where: str, expected: list[str]) -> None:
        assert self._filter_order(where) == expected

    def test_a_comparison_of_a_typed_property_is_fast(self) -> None:
        order = self._filter_order(
            "properties.query.kind = 'deep' AND properties.duration > 7", numeric_properties=("duration",)
        )
        assert order == ["seven", "deep"]

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
