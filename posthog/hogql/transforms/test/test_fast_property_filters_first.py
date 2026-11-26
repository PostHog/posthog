from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database, _use_person_properties_from_events
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
        key = node.keys[0] if node.map_subcolumn is None else node.map_subcolumn.removeprefix("key_")
        if key in MARKERS:
            self.markers.append(MARKERS[key])


class TestFastPropertyFiltersFirst(SimpleTestCase):
    def _filter_order(
        self,
        where: str,
        *,
        query: str = "SELECT count() FROM events WHERE {where}",
        native: bool = True,
        property_types: dict[str, str] | None = None,
        placeholders: dict[str, ast.Expr] | None = None,
        person_properties_on_events: bool = False,
    ) -> list[str]:
        metadata = PropertyMetadata(
            event_properties={name: {"type": property_type} for name, property_type in (property_types or {}).items()}
        )
        database = Database()
        if person_properties_on_events:
            _use_person_properties_from_events(database)
        context = HogQLContext(
            use_new_events_schema=native,
            property_metadata=metadata,
            database=database,
            apply_events_retention_floor=False,
        )
        context.property_swapper = PropertySwapper("UTC", metadata.event_properties, {}, {}, context, False)
        prepared = prepare_ast_for_printing(
            parse_select(query.format(where=where), placeholders), context, "clickhouse"
        )
        assert prepared is not None
        order = _MarkerOrder()
        order.visit(prepared)
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

    @parameterized.expand(
        [
            ("named_in_the_select", "SELECT rowNumberInBlock() AS rn FROM events WHERE {where}"),
            ("named_in_a_with_clause", "WITH rowNumberInBlock() AS rn SELECT count() FROM events WHERE {where}"),
            (
                "named_in_a_with_clause_of_an_outer_query",
                "WITH rowNumberInBlock() AS rn SELECT e FROM (SELECT event AS e FROM events WHERE {where})",
            ),
        ]
    )
    def test_nothing_moves_ahead_of_an_alias_of_a_function_that_numbers_rows(self, _name: str, query: str) -> None:
        order = self._filter_order("rn = length(properties.plan) - 7 AND properties.query_type = 'fast'", query=query)
        assert order == ["seven", "fast"]

    def test_numbering_the_rows_of_a_subquery_leaves_its_filters_free_to_move(self) -> None:
        order = self._filter_order(
            "properties.query.kind = 'deep' AND properties.query_type = 'fast'",
            query="SELECT e, rowNumberInAllBlocks() AS n FROM (SELECT event AS e FROM events WHERE {where})",
        )
        assert order == ["fast", "deep"]

    def test_a_person_property_named_like_a_feature_flag_moves(self) -> None:
        order = self._filter_order(
            "properties.query.kind = 'deep' AND person.properties.`$feature/beta` = 'fast'",
            person_properties_on_events=True,
        )
        assert order == ["fast", "deep"]

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
            "properties.query.kind = 'deep' AND properties.query_type = 'fast'",
            query=f"SELECT count() FROM {table} WHERE {{where}}",
            native=native,
        )
        assert order == ["deep", "fast"]
