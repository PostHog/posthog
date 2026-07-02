from collections.abc import Iterable
from typing import Any, Literal, Optional, Union, cast

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, BaseTest, _create_event, cleanup_materialized_columns
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    EmptyPropertyFilter,
    FlagPropertyFilter,
    HogQLPropertyFilter,
    HogQLQueryModifiers,
    PersonsOnEventsMode,
    PropertyOperator,
    RetentionEntity,
)

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import QueryError
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_expr
from posthog.hogql.printer.utils import prepare_and_print_ast
from posthog.hogql.property import (
    entity_to_expr,
    has_aggregation,
    map_virtual_properties,
    property_to_expr,
    selector_to_expr,
    tag_name_to_expr,
)
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.visitor import clear_locations

from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS, PropertyOperatorType
from posthog.models import Property, PropertyDefinition, Team
from posthog.models.property import PropertyGroup

from products.cohorts.backend.models.cohort import Cohort
from products.data_tools.backend.models.join import DataWarehouseJoin
from products.event_definitions.backend.models.property_definition import PropertyType
from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

from ee.clickhouse.materialized_columns.columns import materialize

elements_chain_match = lambda x: parse_expr("elements_chain =~ {regex}", {"regex": ast.Constant(value=str(x))})
elements_chain_imatch = lambda x: parse_expr("elements_chain =~* {regex}", {"regex": ast.Constant(value=str(x))})
not_call = lambda x: ast.Call(name="not", args=[x])


class TestProperty(BaseTest):
    maxDiff = None

    def _property_to_expr(
        self,
        property: Union[PropertyGroup, Property, HogQLPropertyFilter, dict, list],
        team: Optional[Team] = None,
        scope: Optional[
            Literal["event", "person", "group", "session", "replay", "replay_entity", "revenue_analytics"]
        ] = None,
        strict: bool = True,
    ):
        return clear_locations(
            property_to_expr(property, team=team or self.team, scope=scope or "event", strict=strict)
        )

    def _selector_to_expr(self, selector: str):
        return clear_locations(selector_to_expr(selector))

    def _parse_expr(self, expr: str, placeholders: Optional[dict[str, Any]] = None):
        return clear_locations(parse_expr(expr, placeholders=placeholders))

    def test_has_aggregation(self):
        self.assertEqual(has_aggregation(self._parse_expr("properties.a = 'b'")), False)
        self.assertEqual(has_aggregation(self._parse_expr("if(1,2,3)")), False)
        self.assertEqual(has_aggregation(self._parse_expr("if(1,2,avg(3))")), True)
        self.assertEqual(has_aggregation(self._parse_expr("count()")), True)
        self.assertEqual(has_aggregation(self._parse_expr("sum(properties.bla)")), True)

    def test_property_to_expr_hogql(self):
        self.assertEqual(self._property_to_expr({"type": "hogql", "key": "1"}), ast.Constant(value=1))
        self.assertEqual(
            self._property_to_expr(Property(type="hogql", key="1")),
            ast.Constant(value=1),
        )
        self.assertEqual(
            self._property_to_expr(HogQLPropertyFilter(type="hogql", key="1")),
            ast.Constant(value=1),
        )

    def test_property_to_expr_group(self):
        self.assertEqual(
            self._property_to_expr({"type": "group", "group_type_index": 0, "key": "a", "value": "b"}),
            self._parse_expr("group_0.properties.a = 'b'"),
        )
        self.assertEqual(
            self._property_to_expr({"type": "group", "group_type_index": 3, "key": "a", "value": "b"}),
            self._parse_expr("group_3.properties.a = 'b'"),
        )
        self.assertEqual(
            self._parse_expr("group_0.properties.a = NULL"),
            self._property_to_expr(
                {"type": "group", "group_type_index": 0, "key": "a", "value": "b", "operator": "is_not_set"}
            ),
        )
        self.assertEqual(
            self._property_to_expr(Property(type="group", group_type_index=0, key="a", value=["b", "c"])),
            self._parse_expr("group_0.properties.a in ('b', 'c')"),
        )

        # Missing group_type_index
        self.assertEqual(
            self._property_to_expr({"type": "group", "key": "a", "value": "b"}, strict=False), self._parse_expr("1")
        )

    def test_property_to_expr_group_scope(self):
        self.assertEqual(
            self._property_to_expr(
                {"type": "group", "group_type_index": 0, "key": "name", "value": "Hedgebox Inc."}, scope="group"
            ),
            self._parse_expr("properties.name = 'Hedgebox Inc.'"),
        )

        self.assertEqual(
            self._property_to_expr(
                Property(type="group", group_type_index=0, key="a", value=["b", "c"]), scope="group"
            ),
            self._parse_expr("properties.a in ('b', 'c')"),
        )

        self.assertEqual(
            self._property_to_expr(
                Property(type="group", group_type_index=0, key="arr", operator="gt", value=100), scope="group"
            ),
            self._parse_expr("properties.arr > 100"),
        )

    def test_property_to_expr_group_booleans(self):
        PropertyDefinition.objects.create(
            team=self.team,
            name="boolean_prop",
            type=PropertyDefinition.Type.GROUP,
            group_type_index=0,
            property_type=PropertyType.Boolean,
        )
        self.assertEqual(
            self._property_to_expr({"type": "group", "group_type_index": 0, "key": "boolean_prop", "value": ["true"]}),
            self._parse_expr("group_0.properties.boolean_prop = true"),
        )

    def test_property_to_expr_event(self):
        self.assertEqual(
            self._property_to_expr({"key": "a", "value": "b"}),
            self._parse_expr("properties.a = 'b'"),
        )
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "a", "value": "b"}),
            self._parse_expr("properties.a = 'b'"),
        )
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "a", "value": "b", "operator": "is_set"}),
            self._parse_expr("properties.a != NULL"),
        )
        self.assertEqual(
            self._parse_expr("properties.a = NULL"),
            self._property_to_expr({"type": "event", "key": "a", "value": "b", "operator": "is_not_set"}),
        )
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "a", "value": "b", "operator": "exact"}),
            self._parse_expr("properties.a = 'b'"),
        )
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "a", "value": "b", "operator": "is_not"}),
            self._parse_expr("properties.a != 'b'"),
        )
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "a", "value": "3", "operator": "gt"}),
            self._parse_expr("properties.a > '3'"),
        )
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "a", "value": "3", "operator": "lt"}),
            self._parse_expr("properties.a < '3'"),
        )
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "a", "value": "3", "operator": "gte"}),
            self._parse_expr("properties.a >= '3'"),
        )
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "a", "value": "3", "operator": "lte"}),
            self._parse_expr("properties.a <= '3'"),
        )
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "a", "value": "3", "operator": "icontains"}),
            self._parse_expr("toString(properties.a) ilike '%3%'"),
        )
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "a", "value": "3", "operator": "not_icontains"}),
            self._parse_expr("toString(properties.a) not ilike '%3%'"),
        )
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "a", "value": ".*", "operator": "regex"}),
            self._parse_expr("ifNull(match(toString(properties.a), '.*'), 0)"),
        )
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "a", "value": ".*", "operator": "not_regex"}),
            self._parse_expr("ifNull(not(match(toString(properties.a), '.*')), true)"),
        )
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "a", "value": [], "operator": "exact"}),
            self._parse_expr("true"),
        )
        self.assertEqual(
            self._parse_expr("1"),
            self._property_to_expr(
                {"type": "event", "key": "a", "operator": "icontains"}, strict=False
            ),  # value missing
        )
        self.assertEqual(
            self._parse_expr("1"),
            self._property_to_expr({}, strict=False),  # incomplete event
        )
        self.assertEqual(
            self._parse_expr("1"),
            self._property_to_expr(EmptyPropertyFilter()),  # type: ignore
        )

    def test_property_to_expr_boolean(self):
        PropertyDefinition.objects.create(
            team=self.team,
            name="boolean_prop",
            type=PropertyDefinition.Type.EVENT,
            property_type=PropertyType.Boolean,
        )
        PropertyDefinition.objects.create(
            team=self.team,
            name="string_prop",
            type=PropertyDefinition.Type.EVENT,
            property_type=PropertyType.String,
        )
        self.assertEqual(
            self._property_to_expr(
                {"type": "event", "key": "boolean_prop", "value": "true"},
                team=self.team,
            ),
            self._parse_expr("properties.boolean_prop = true"),
        )
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "string_prop", "value": "true"}, team=self.team),
            self._parse_expr("properties.string_prop = 'true'"),
        )
        self.assertEqual(
            self._property_to_expr(
                {"type": "event", "key": "boolean_prop", "value": "false"},
                team=self.team,
            ),
            self._parse_expr("properties.boolean_prop = false"),
        )
        self.assertEqual(
            self._property_to_expr(
                {"type": "event", "key": "unknown_prop", "value": "true"},
                team=self.team,
            ),
            self._parse_expr(
                "properties.unknown_prop = 'true'"  # We don't have a type for unknown_prop, so string comparison it is
            ),
        )
        # Python boolean True (not string "true") should also work
        self.assertEqual(
            self._property_to_expr(
                {"type": "event", "key": "boolean_prop", "value": True},
                team=self.team,
            ),
            self._parse_expr("properties.boolean_prop = true"),
        )
        self.assertEqual(
            self._property_to_expr(
                {"type": "event", "key": "string_prop", "value": True},
                team=self.team,
            ),
            self._parse_expr("properties.string_prop = 'true'"),
        )
        self.assertEqual(
            self._property_to_expr(
                {"type": "event", "key": "boolean_prop", "value": False},
                team=self.team,
            ),
            self._parse_expr("properties.boolean_prop = false"),
        )
        self.assertEqual(
            self._property_to_expr(
                {"type": "event", "key": "unknown_prop", "value": True},
                team=self.team,
            ),
            self._parse_expr("properties.unknown_prop = 'true'"),
        )

    @parameterized.expand(
        [
            (
                "is_date_before_iso",
                "event",
                "a",
                "2026-03-19T14:00:00Z",
                "is_date_before",
                ast.CompareOperationOp.Lt,
                "2026-03-19T14:00:00Z",
            ),
            (
                "is_date_after_iso",
                "event",
                "a",
                "2026-03-19T14:00:00Z",
                "is_date_after",
                ast.CompareOperationOp.Gt,
                "2026-03-19T14:00:00Z",
            ),
            (
                "is_date_exact_date_only",
                "event",
                "a",
                "2026-03-19",
                "is_date_exact",
                ast.CompareOperationOp.Eq,
                "2026-03-19",
            ),
            (
                "person_is_date_before_iso",
                "person",
                "inserted_at",
                "2026-03-19T14:00:00Z",
                "is_date_before",
                ast.CompareOperationOp.Lt,
                "2026-03-19T14:00:00Z",
            ),
        ]
    )
    def test_property_to_expr_date_operator(self, _name, prop_type, key, value, operator, op, expected_rhs):
        chain = ["person", "properties", key] if prop_type == "person" else ["properties", key]
        self.assertEqual(
            self._property_to_expr({"type": prop_type, "key": key, "value": value, "operator": operator}),
            ast.CompareOperation(
                op=op,
                left=ast.Call(
                    name="toDateTime",
                    args=[ast.Call(name="toString", args=[ast.Field(chain=chain)])],
                ),
                right=ast.Call(name="toDateTime", args=[ast.Constant(value=expected_rhs)]),
            ),
        )

    def test_property_to_expr_generic_lt_gt_unchanged(self):
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "a", "value": "3", "operator": "lt"}),
            self._parse_expr("properties.a < '3'"),
        )
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "a", "value": "3", "operator": "gt"}),
            self._parse_expr("properties.a > '3'"),
        )

    @parameterized.expand(
        [
            ("exact", "exact", ast.CompareOperationOp.Eq),
            ("is_not", "is_not", ast.CompareOperationOp.NotEq),
            ("lt", "lt", ast.CompareOperationOp.Lt),
            ("gt", "gt", ast.CompareOperationOp.Gt),
            ("lte", "lte", ast.CompareOperationOp.LtEq),
            ("gte", "gte", ast.CompareOperationOp.GtEq),
        ]
    )
    def test_property_to_expr_offset_datetime_coerced(self, _name, operator, op):
        # An ISO datetime string with a timezone offset (what datetime.isoformat() emits) can't be
        # implicitly cast against a DateTime64 column, so both sides must go through toDateTime.
        value = "2026-07-02T15:12:33.156828+00:00"
        self.assertEqual(
            self._property_to_expr(
                {"type": "person_metadata", "key": "created_at", "value": value, "operator": operator},
                scope="person",
            ),
            ast.CompareOperation(
                op=op,
                left=ast.Call(
                    name="toDateTime", args=[ast.Call(name="toString", args=[ast.Field(chain=["created_at"])])]
                ),
                right=ast.Call(name="toDateTime", args=[ast.Constant(value=value)]),
            ),
        )

    @parameterized.expand(
        [
            ("is_date_before_relative", "-10m", "is_date_before", ast.CompareOperationOp.Lt, "2025-06-09 12:00:00"),
            ("is_date_after_relative", "-7d", "is_date_after", ast.CompareOperationOp.Gt, "2026-04-02 12:00:00"),
            ("is_date_exact_relative", "-1y", "is_date_exact", ast.CompareOperationOp.Eq, "2025-04-09 12:00:00"),
        ]
    )
    @freeze_time("2026-04-09T12:00:00Z")
    def test_property_to_expr_date_operator_relative(self, _name, value, operator, op, expected_rhs):
        result = self._property_to_expr({"type": "event", "key": "a", "value": value, "operator": operator})
        assert isinstance(result, ast.CompareOperation)
        assert result.op == op
        assert isinstance(result.right, ast.Call)
        assert result.right.name == "toDateTime"
        assert len(result.right.args) == 1
        assert isinstance(result.right.args[0], ast.Constant)
        assert result.right.args[0].value == expected_rhs

    def test_property_to_expr_event_list(self):
        # positive
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "a", "value": ["b", "c"], "operator": "exact"}),
            self._parse_expr("properties.a in ('b', 'c')"),
        )
        self.assertEqual(
            self._property_to_expr(
                {
                    "type": "event",
                    "key": "a",
                    "value": ["b", "c"],
                    "operator": "icontains",
                }
            ),
            self._parse_expr("multiSearchAnyCaseInsensitive(toString(properties.a), ['b', 'c']) > 0"),
        )
        a = self._property_to_expr({"type": "event", "key": "a", "value": ["b", "c"], "operator": "regex"})
        self.assertEqual(
            a,
            self._parse_expr(
                "ifNull(match(toString(properties.a), 'b'), 0) or ifNull(match(toString(properties.a), 'c'), 0)"
            ),
        )
        # Want to make sure this returns 0, not false. Clickhouse uses UInt8s primarily for booleans.
        self.assertIs(0, a.exprs[1].args[1].value)
        # negative
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "a", "value": ["b", "c"], "operator": "is_not"}),
            self._parse_expr("properties.a not in ('b', 'c')"),
        )
        self.assertEqual(
            self._property_to_expr(
                {
                    "type": "event",
                    "key": "a",
                    "value": ["b", "c"],
                    "operator": "not_icontains",
                }
            ),
            self._parse_expr("multiSearchAnyCaseInsensitive(toString(properties.a), ['b', 'c']) = 0"),
        )
        a = self._property_to_expr(
            {
                "type": "event",
                "key": "a",
                "value": ["b", "c"],
                "operator": "not_regex",
            }
        )
        self.assertEqual(
            a,
            self._parse_expr(
                "ifNull(not(match(toString(properties.a), 'b')), 1) and ifNull(not(match(toString(properties.a), 'c')), 1)"
            ),
        )
        self.assertIs(1, a.exprs[1].args[1].value)

    def test_property_to_expr_feature(self):
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "a", "value": "b", "operator": "exact"}),
            self._parse_expr("properties.a = 'b'"),
        )

    def test_property_to_expr_person(self):
        self.assertEqual(
            self._property_to_expr({"type": "person", "key": "a", "value": "b", "operator": "exact"}),
            self._parse_expr("person.properties.a = 'b'"),
        )

    def test_property_to_expr_error_tracking_issue_properties(self):
        self.assertEqual(
            self._property_to_expr(
                {
                    "type": "event",
                    "key": "$exception_types",
                    "value": "ReferenceError",
                    "operator": "icontains",
                }
            ),
            self._parse_expr(
                "arrayExists(v -> toString(v) ilike '%ReferenceError%', JSONExtract(ifNull(properties.$exception_types, ''), 'Array(String)'))"
            ),
        )
        self.assertEqual(
            self._property_to_expr(
                {
                    "type": "event",
                    "key": "$exception_types",
                    "value": ["ReferenceError", "TypeError"],
                    "operator": "exact",
                }
            ),
            self._parse_expr(
                "arrayExists(v -> v in ('ReferenceError', 'TypeError'), JSONExtract(ifNull(properties.$exception_types, ''), 'Array(String)'))"
            ),
        )
        self.assertEqual(
            self._property_to_expr(
                {
                    "type": "event",
                    "key": "$exception_types",
                    "value": ["ReferenceError", "TypeError"],
                    "operator": "is_not",
                }
            ),
            self._parse_expr(
                "arrayExists(v -> v not in ('ReferenceError', 'TypeError'), JSONExtract(ifNull(properties.$exception_types, ''), 'Array(String)'))"
            ),
        )
        self.assertEqual(
            self._property_to_expr(
                {
                    "key": "$exception_types",
                    "value": "ValidationError",
                    "operator": "not_regex",
                    "type": "event",
                }
            ),
            self._parse_expr(
                "arrayExists(v -> ifNull(not(match(toString(v), 'ValidationError')), 1), JSONExtract(ifNull(properties.$exception_types, ''), 'Array(String)'))"
            ),
        )
        self.assertEqual(
            self._property_to_expr(
                {
                    "type": "event",
                    "key": "$exception_types",
                    "value": "ValidationError",
                    "operator": "icontains",
                }
            ),
            self._parse_expr(
                "arrayExists(v -> toString(v) ILIKE '%ValidationError%', JSONExtract(ifNull(properties.$exception_types, ''), 'Array(String)'))"
            ),
        )
        self.assertEqual(
            self._property_to_expr(
                {
                    "type": "event",
                    "key": "$exception_types",
                    "value": "ValidationError",
                    "operator": "not_icontains",
                }
            ),
            self._parse_expr(
                "arrayExists(v -> toString(v) NOT ILIKE '%ValidationError%', JSONExtract(ifNull(properties.$exception_types, ''), 'Array(String)'))"
            ),
        )
        self.assertEqual(
            self._property_to_expr(
                {
                    "type": "event",
                    "key": "$exception_types",
                    "value": ["ReferenceError", "TypeError"],
                    "operator": "icontains",
                }
            ),
            self._parse_expr(
                "arrayExists(v -> multiSearchAnyCaseInsensitive(toString(v), ['ReferenceError', 'TypeError']) > 0, JSONExtract(ifNull(properties.$exception_types, ''), 'Array(String)'))"
            ),
        )
        self.assertEqual(
            self._property_to_expr(
                {
                    "type": "event",
                    "key": "$exception_types",
                    "value": ["ReferenceError", "TypeError"],
                    "operator": "not_icontains",
                }
            ),
            self._parse_expr(
                "arrayExists(v -> multiSearchAnyCaseInsensitive(toString(v), ['ReferenceError', 'TypeError']) = 0, JSONExtract(ifNull(properties.$exception_types, ''), 'Array(String)'))"
            ),
        )

    def test_property_to_expr_multiSearch_edge_cases(self):
        # Test empty array with icontains - falls back to single value logic
        result = self._property_to_expr(
            {
                "type": "event",
                "key": "a",
                "value": [],
                "operator": "icontains",
            }
        )
        # Empty arrays are treated as single values, converted to string representation
        expected = self._parse_expr("toString(properties.a) ILIKE '%[]%'")
        self.assertEqual(result, expected)

        # Test single-element array with icontains - should use ILIKE, not multiSearch
        result = self._property_to_expr(
            {
                "type": "event",
                "key": "a",
                "value": ["single"],
                "operator": "icontains",
            }
        )
        expected = self._parse_expr("toString(properties.a) ILIKE '%single%'")
        self.assertEqual(result, expected)

        # Test single-element array with not_icontains - should use NOT ILIKE, not multiSearch
        result = self._property_to_expr(
            {
                "type": "event",
                "key": "a",
                "value": ["single"],
                "operator": "not_icontains",
            }
        )
        expected = self._parse_expr("toString(properties.a) NOT ILIKE '%single%'")
        self.assertEqual(result, expected)

        # Test non-string values being stringified
        self.assertEqual(
            self._property_to_expr(
                {
                    "type": "event",
                    "key": "a",
                    "value": [123, 456.78, True],
                    "operator": "icontains",
                }
            ),
            self._parse_expr("multiSearchAnyCaseInsensitive(toString(properties.a), ['123', '456.78', 'True']) > 0"),
        )

    def test_property_to_expr_element(self):
        self.assertEqual(
            self._property_to_expr(
                {
                    "type": "element",
                    "key": "selector",
                    "value": "div",
                    "operator": "exact",
                }
            ),
            self._selector_to_expr("div"),
        )
        self.assertEqual(
            self._property_to_expr(
                {
                    "type": "element",
                    "key": "selector",
                    "value": "div",
                    "operator": "is_not",
                }
            ),
            clear_locations(not_call(self._selector_to_expr("div"))),
        )
        self.assertEqual(
            self._property_to_expr(
                {
                    "type": "element",
                    "key": "tag_name",
                    "value": "div",
                    "operator": "exact",
                }
            ),
            clear_locations(tag_name_to_expr("div")),
        )
        self.assertEqual(
            self._property_to_expr(
                {
                    "type": "element",
                    "key": "tag_name",
                    "value": "div",
                    "operator": "is_not",
                }
            ),
            clear_locations(not_call(tag_name_to_expr("div"))),
        )
        self.assertEqual(
            self._property_to_expr(
                {
                    "type": "element",
                    "key": "href",
                    "value": "href-text.",
                    "operator": "exact",
                }
            ),
            self._parse_expr("elements_chain_href = 'href-text.'"),
        )
        self.assertEqual(
            self._property_to_expr(
                {
                    "type": "element",
                    "key": "href",
                    "value": "href-text.",
                    "operator": "icontains",
                }
            ),
            self._parse_expr("toString(elements_chain_href) ilike '%href-text.%'"),
        )
        self.assertEqual(
            self._property_to_expr(
                {
                    "type": "element",
                    "key": "text",
                    "value": "text-text.",
                    "operator": "regex",
                }
            ),
            self._parse_expr(
                "arrayExists(text -> ifNull(match(toString(text), 'text-text.'), 0), elements_chain_texts)"
            ),
        )

    def test_property_groups(self):
        self.assertEqual(
            self._property_to_expr(
                PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[],
                )
            ),
            self._parse_expr("true"),
        )

        self.assertEqual(
            self._property_to_expr(
                PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(type="person", key="a", value="b", operator="exact"),
                        Property(type="event", key="e", value="b", operator="exact"),
                    ],
                )
            ),
            self._parse_expr("person.properties.a = 'b' and properties.e = 'b'"),
        )

        self.assertEqual(
            self._property_to_expr(
                PropertyGroup(
                    type=PropertyOperatorType.OR,
                    values=[
                        Property(type="person", key="a", value="b", operator="exact"),
                        Property(type="event", key="e", value="b", operator="exact"),
                    ],
                )
            ),
            self._parse_expr("person.properties.a = 'b' or properties.e = 'b'"),
        )

    def test_property_groups_single(self):
        self.assertEqual(
            self._property_to_expr(
                PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(type="person", key="a", value="b", operator="exact"),
                    ],
                )
            ),
            self._parse_expr("person.properties.a = 'b'"),
        )

        self.assertEqual(
            self._property_to_expr(
                PropertyGroup(
                    type=PropertyOperatorType.OR,
                    values=[Property(type="event", key="e", value="b", operator="exact")],
                )
            ),
            self._parse_expr("properties.e = 'b'"),
        )

    def test_property_groups_combined(self):
        self.assertEqual(
            self._property_to_expr(
                PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=cast(
                        Union[list[Property], list[PropertyGroup]],
                        [
                            Property(type="person", key="a", value="b", operator="exact"),
                            PropertyGroup(
                                type=PropertyOperatorType.OR,
                                values=[
                                    Property(
                                        type="person",
                                        key="a",
                                        value="b",
                                        operator="exact",
                                    ),
                                    Property(
                                        type="event",
                                        key="e",
                                        value="b",
                                        operator="exact",
                                    ),
                                ],
                            ),
                        ],
                    ),
                )
            ),
            self._parse_expr("person.properties.a = 'b' and (person.properties.a = 'b' or properties.e = 'b')"),
        )

    def test_tag_name_to_expr(self):
        self.assertEqual(
            clear_locations(tag_name_to_expr("a")),
            clear_locations(elements_chain_match("(^|;)a(\\.|$|;|:)")),
        )

    def test_selector_to_expr(self):
        self.assertEqual(
            self._selector_to_expr("div"),
            clear_locations(
                elements_chain_match('(^|;)div([-_a-zA-Z0-9\\.:"= \\[\\]\\(\\),]*?)?($|;|:([^;^\\s]*(;|$|\\s)))')
            ),
        )
        self.assertEqual(
            self._selector_to_expr("div > div"),
            clear_locations(
                elements_chain_match(
                    '(^|;)div([-_a-zA-Z0-9\\.:"= \\[\\]\\(\\),]*?)?($|;|:([^;^\\s]*(;|$|\\s)))div([-_a-zA-Z0-9\\.:"= \\[\\]\\(\\),]*?)?($|;|:([^;^\\s]*(;|$|\\s))).*'
                )
            ),
        )
        self.assertEqual(
            self._selector_to_expr("a[href='boo']"),
            clear_locations(
                parse_expr(
                    "{regex} and arrayCount(x -> x IN ['a'], elements_chain_elements) > 0",
                    {
                        "regex": elements_chain_match(
                            '(^|;)a.*?href="boo".*?([-_a-zA-Z0-9\\.:"= \\[\\]\\(\\),]*?)?($|;|:([^;^\\s]*(;|$|\\s)))'
                        )
                    },
                )
            ),
        )
        self.assertEqual(
            self._selector_to_expr(".class"),
            clear_locations(
                elements_chain_match(
                    '(^|;).*?\\.class([-_a-zA-Z0-9\\.:"= \\[\\]\\(\\),]*?)?($|;|:([^;^\\s]*(;|$|\\s)))'
                )
            ),
        )
        self.assertEqual(
            self._selector_to_expr("a#withid"),
            clear_locations(
                parse_expr(
                    """{regex} and indexOf(elements_chain_ids, 'withid') > 0 and arrayCount(x -> x IN ['a'], elements_chain_elements) > 0""",
                    {
                        "regex": elements_chain_match(
                            '(^|;)a.*?attr_id="withid".*?([-_a-zA-Z0-9\\.:"= \\[\\]\\(\\),]*?)?($|;|:([^;^\\s]*(;|$|\\s)))'
                        )
                    },
                )
            ),
        )

        self.assertEqual(
            self._selector_to_expr("a#with-dashed-id"),
            clear_locations(
                parse_expr(
                    """{regex} and indexOf(elements_chain_ids, 'with-dashed-id') > 0 and arrayCount(x -> x IN ['a'], elements_chain_elements) > 0""",
                    {
                        "regex": elements_chain_match(
                            '(^|;)a.*?attr_id="with\\-dashed\\-id".*?([-_a-zA-Z0-9\\.:"= \\[\\]\\(\\),]*?)?($|;|:([^;^\\s]*(;|$|\\s)))'
                        )
                    },
                )
            ),
        )
        # test optimization
        self.assertEqual(
            self._selector_to_expr("#with-dashed-id"),
            clear_locations(parse_expr("""indexOf(elements_chain_ids, 'with-dashed-id') > 0""")),
        )
        self.assertEqual(
            self._selector_to_expr("#with-dashed-id"),
            self._selector_to_expr("[id='with-dashed-id']"),
        )
        self.assertEqual(
            self._selector_to_expr("#with\\slashed\\id"),
            clear_locations(
                parse_expr(
                    "indexOf(elements_chain_ids, 'with\\\\slashed\\\\id') > 0",
                )
            ),
        )

    def test_selector_to_expr_tailwind_classes(self):
        """Test that selectors work with Tailwind classes that include brackets, parentheses, and commas"""
        # Test Tailwind class with brackets (responsive design)
        self.assertEqual(
            self._selector_to_expr(".sm:[max-width:640px]"),
            clear_locations(
                elements_chain_match(
                    '(^|;).*?\\.sm:\\[max\\-width:640px\\]([-_a-zA-Z0-9\\.:"= \\[\\]\\(\\),]*?)?($|;|:([^;^\\s]*(;|$|\\s)))'
                )
            ),
        )

        # Test Tailwind class with parentheses and commas (calc functions)
        self.assertEqual(
            self._selector_to_expr(".w-[calc(100%-2rem)]"),
            clear_locations(
                elements_chain_match(
                    '(^|;).*?\\.w\\-\\[calc\\(100%\\-2rem\\)\\]([-_a-zA-Z0-9\\.:"= \\[\\]\\(\\),]*?)?($|;|:([^;^\\s]*(;|$|\\s)))'
                )
            ),
        )

        # Test Tailwind class with complex values including commas
        self.assertEqual(
            self._selector_to_expr(".shadow-[0_4px_6px_rgba(0,0,0,0.1)]"),
            clear_locations(
                elements_chain_match(
                    '(^|;).*?\\.shadow\\-\\[0_4px_6px_rgba\\(0,0,0,0\\.1\\)\\]([-_a-zA-Z0-9\\.:"= \\[\\]\\(\\),]*?)?($|;|:([^;^\\s]*(;|$|\\s)))'
                )
            ),
        )

    def test_cohort_filter_static(self):
        cohort = Cohort.objects.create(
            team=self.team,
            is_static=True,
            groups=[{"properties": [{"key": "$os", "value": "Chrome", "type": "person"}]}],
        )
        self.assertEqual(
            self._property_to_expr({"type": "cohort", "key": "id", "value": cohort.pk}, self.team),
            self._parse_expr(f"person_id IN COHORT {cohort.pk}"),
        )

    def test_cohort_filter_dynamic(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$os", "value": "Chrome", "type": "person"}]}],
        )
        self.assertEqual(
            self._property_to_expr({"type": "cohort", "key": "id", "value": cohort.pk}, self.team),
            self._parse_expr(f"person_id IN COHORT {cohort.pk}"),
        )

    def test_person_scope(self):
        self.assertEqual(
            self._property_to_expr(
                {"type": "person", "key": "a", "value": "b", "operator": "exact"},
                scope="event",
            ),
            self._parse_expr("person.properties.a = 'b'"),
        )
        self.assertEqual(
            self._property_to_expr(
                {"type": "person", "key": "a", "value": "b", "operator": "exact"},
                scope="person",
            ),
            self._parse_expr("properties.a = 'b'"),
        )
        with self.assertRaises(Exception) as e:
            self._property_to_expr(
                {"type": "event", "key": "a", "value": "b", "operator": "exact"},
                scope="person",
            )
        self.assertEqual(
            str(e.exception),
            "The 'event' property filter does not work in 'person' scope",
        )

    @parameterized.expand(
        [
            ("event_scope", "event", "distinct_id = 'abc'"),
            ("person_scope", "person", "pdi.distinct_id = 'abc'"),
        ]
    )
    def test_person_distinct_id_property(self, _name, scope, expected_expr):
        # distinct_id is not stored in person.properties — it's the events.distinct_id column
        # in event scope, and reachable via the pdi lazy join in person scope.
        self.assertEqual(
            self._property_to_expr(
                {"type": "person", "key": "distinct_id", "value": "abc", "operator": "exact"},
                scope=scope,
            ),
            self._parse_expr(expected_expr),
        )

    @parameterized.expand(
        [
            ("disabled", PersonsOnEventsMode.DISABLED),
            ("no_override_props_on_events", PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS),
            ("override_props_on_events", PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS),
            ("override_props_joined", PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED),
        ]
    )
    def test_person_distinct_id_property_resolves_under_all_poe_modes(self, _name, mode):
        # Regression test for "Field not found: pdi" — previously, the special case for
        # {type: person, key: distinct_id} routed through events.person.pdi, which broke under
        # person-on-events modes that rebind events.person to the `poe` virtual table.
        expr = property_to_expr(
            {"type": "person", "key": "distinct_id", "value": "abc", "operator": "is_not"},
            team=self.team,
            scope="event",
        )
        query_ast = ast.SelectQuery(
            select=[ast.Call(name="count", args=[])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=expr,
        )
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            modifiers=create_default_modifiers_for_team(self.team, HogQLQueryModifiers(personsOnEventsMode=mode)),
        )
        sql, _ = prepare_and_print_ast(query_ast, context=context, dialect="clickhouse")
        # Used to raise QueryError("Field not found: pdi") under PoE modes that rebind
        # events.person to the `poe` virtual table.
        assert "distinct_id" in sql
        assert "pdi" not in sql

    def test_entity_to_expr_actions_type_with_id(self):
        action_mock = MagicMock()
        with patch("products.actions.backend.models.action.Action.objects.get", return_value=action_mock):
            entity = RetentionEntity(**{"type": TREND_FILTER_TYPE_ACTIONS, "id": 123})
            result = entity_to_expr(entity, self.team)
            self.assertIsInstance(result, ast.Expr)

    def test_entity_to_expr_events_type_with_id(self):
        entity = RetentionEntity(**{"type": TREND_FILTER_TYPE_EVENTS, "id": "event_id"})
        result = clear_locations(entity_to_expr(entity, self.team))
        expected = ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["events", "event"]),
            right=ast.Constant(value="event_id"),
        )
        self.assertEqual(result, expected)

    def test_entity_to_expr_events_type_without_id(self):
        entity = RetentionEntity(**{"type": TREND_FILTER_TYPE_EVENTS, "id": None})
        result = entity_to_expr(entity, self.team)
        self.assertEqual(result, ast.Constant(value=True))

    def test_entity_to_expr_default_case(self):
        entity = RetentionEntity()
        result = entity_to_expr(entity, self.team)
        self.assertEqual(result, ast.Constant(value=True))

    def test_session_duration(self):
        self.assertEqual(
            self._property_to_expr(
                {"type": "session", "key": "$session_duration", "value": 10, "operator": "exact"},
                scope="event",
            ),
            self._parse_expr("session.$session_duration = 10"),
        )

    def test_session_boolean_property(self):
        self.assertEqual(
            self._property_to_expr(
                {"type": "session", "key": "$is_bounce", "value": "true", "operator": "exact"},
                scope="event",
            ),
            self._parse_expr("session.$is_bounce = true"),
        )
        self.assertEqual(
            self._property_to_expr(
                {"type": "session", "key": "$is_bounce", "value": "false", "operator": "exact"},
                scope="event",
            ),
            self._parse_expr("session.$is_bounce = false"),
        )

    def test_data_warehouse_person_property(self):
        credential = DataWarehouseCredential.objects.create(
            team=self.team, access_key="_accesskey", access_secret="_secret"
        )
        DataWarehouseTable.objects.create(
            team=self.team,
            name="extended_properties",
            columns={
                "string_prop": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)"},
                "int_prop": {"hogql": "IntegerDatabaseField", "clickhouse": "Nullable(Int64)"},
                "bool_prop": {"hogql": "BooleanDatabaseField", "clickhouse": "Nullable(Bool)"},
            },
            credential=credential,
            url_pattern="",
        )

        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="persons",
            source_table_key="properties.email",
            joining_table_name="extended_properties",
            joining_table_key="string_prop",
            field_name="extended_properties",
        )

        self.assertEqual(
            self._property_to_expr(
                {
                    "type": "data_warehouse_person_property",
                    "key": "extended_properties.bool_prop",
                    "value": "true",
                    "operator": "exact",
                }
            ),
            self._parse_expr("person.extended_properties.bool_prop = true"),
        )

    def test_data_warehouse_property_with_list_values(self):
        credential = DataWarehouseCredential.objects.create(
            team=self.team, access_key="_accesskey", access_secret="_secret"
        )
        DataWarehouseTable.objects.create(
            team=self.team,
            name="foobars",
            columns={
                "event": {"hogql": "StringDatabaseField", "clickhouse": "String"},
                "properties": {"hogql": "JSONField", "clickhouse": "String"},
            },
            credential=credential,
            url_pattern="",
        )

        expr = self._property_to_expr(
            Property(
                type="data_warehouse",
                key="foobars.properties.$feature/test",
                value=["control", "test"],
                operator="exact",
            ),
            self.team,
        )

        self.assertIsInstance(expr, ast.Or)
        self.assertEqual(len(expr.exprs), 2)

        # First expression
        compare_op_1 = expr.exprs[0]
        self.assertIsInstance(compare_op_1, ast.CompareOperation)
        self.assertIsInstance(compare_op_1.left, ast.Field)
        self.assertEqual(compare_op_1.left.chain, ["foobars", "properties", "$feature/test"])
        self.assertEqual(compare_op_1.right.value, "control")

        # Second expression
        compare_op_2 = expr.exprs[1]
        self.assertIsInstance(compare_op_2, ast.CompareOperation)
        self.assertIsInstance(compare_op_2.left, ast.Field)
        self.assertEqual(compare_op_2.left.chain, ["foobars", "properties", "$feature/test"])
        self.assertEqual(compare_op_2.right.value, "test")

    def test_revenue_analytics_property(self):
        self.assertEqual(
            self._property_to_expr(
                {
                    "type": "revenue_analytics",
                    "key": "revenue_analytics_product.name",
                    "value": ["Product A"],
                    "operator": "exact",
                },
                scope="revenue_analytics",
            ),
            self._parse_expr("revenue_analytics_product.name = 'Product A'"),
        )

    def test_revenue_analytics_property_multiple_values(self):
        self.assertEqual(
            self._property_to_expr(
                {
                    "type": "revenue_analytics",
                    "key": "revenue_analytics_product.name",
                    "value": ["Product A", "Product C"],
                    "operator": "exact",
                },
                scope="revenue_analytics",
            ),
            self._parse_expr("revenue_analytics_product.name IN ('Product A', 'Product C')"),
        )

    def test_property_to_expr_event_metadata(self):
        self.assertEqual(
            self._property_to_expr(
                {"type": "event_metadata", "key": "distinct_id", "value": "p3", "operator": "exact"},
                scope="event",
            ),
            self._parse_expr("distinct_id = 'p3'"),
        )
        self.assertEqual(
            self._property_to_expr(
                {"type": "event_metadata", "key": "distinct_id", "value": ["p3", "p4"], "operator": "exact"},
                scope="event",
            ),
            self._parse_expr("distinct_id in ('p3', 'p4')"),
        )

    def test_property_to_expr_group_key_numeric_value(self):
        # Group keys ($group_0–$group_4) are string columns. A numeric filter value
        # would crash ClickHouse with NO_COMMON_TYPE, so it is coerced to a string.
        self.assertEqual(
            self._property_to_expr(
                {"type": "event_metadata", "key": "$group_0", "value": 13, "operator": "exact"}, scope="event"
            ),
            self._parse_expr("$group_0 = '13'"),
        )
        # an integer-valued float coerces to the plain integer string (13.0 -> '13')
        self.assertEqual(
            self._property_to_expr(
                {"type": "event_metadata", "key": "$group_2", "value": 13.0, "operator": "is_not"}, scope="event"
            ),
            self._parse_expr("$group_2 != '13'"),
        )
        self.assertEqual(
            self._property_to_expr(
                {"type": "event_metadata", "key": "$group_0", "value": [13, 14], "operator": "exact"}, scope="event"
            ),
            self._parse_expr("$group_0 in ('13', '14')"),
        )
        # a string value is unchanged
        self.assertEqual(
            self._property_to_expr(
                {"type": "event_metadata", "key": "$group_0", "value": "13", "operator": "exact"}, scope="event"
            ),
            self._parse_expr("$group_0 = '13'"),
        )
        # a non-group-key property is left alone — the coercion is scoped to group keys
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "price", "value": 13, "operator": "exact"}),
            self._parse_expr("properties.price = 13"),
        )

    def test_property_to_expr_event_metadata_invalid_scope(self):
        with self.assertRaises(Exception) as e:
            self._property_to_expr(
                {"type": "event_metadata", "key": "distinct_id", "value": "p3", "operator": "exact"},
                scope="person",
            )
        self.assertEqual(
            str(e.exception),
            "The 'event_metadata' property filter does not work in 'person' scope",
        )

    @parameterized.expand(
        [
            # (name, scope, key, operator, value, expected_expr, expected_error)
            (
                "event_scope",
                "event",
                "created_at",
                "is_date_after",
                "2024-01-01",
                "toDateTime(toString(person.created_at)) > toDateTime('2024-01-01')",
                None,
            ),
            (
                "person_scope",
                "person",
                "created_at",
                "is_date_before",
                "2024-01-01",
                "toDateTime(toString(created_at)) < toDateTime('2024-01-01')",
                None,
            ),
            (
                "unsupported_field",
                "event",
                "is_identified",
                "exact",
                True,
                None,
                "Unsupported person_metadata field",
            ),
        ]
    )
    def test_property_to_expr_person_metadata(self, _name, scope, key, operator, value, expected_expr, expected_error):
        prop = {"type": "person_metadata", "key": key, "value": value, "operator": operator}
        if expected_error is not None:
            with self.assertRaises(Exception) as e:
                self._property_to_expr(prop, scope=scope)
            self.assertIn(expected_error, str(e.exception))
        else:
            self.assertEqual(self._property_to_expr(prop, scope=scope), self._parse_expr(expected_expr))

    def test_person_metadata_fields_match_taxonomy(self):
        """
        Guards Python ↔ taxonomy drift only: asserts PERSON_METADATA_FIELDS matches the
        "person_metadata" group in core-filter-definitions-by-group.json.

        NOTE: person_metadata fields are also declared in propertyDefinitionsModel.ts
        (personMetadataPropertyDefinitions), which this test does NOT check. The Rust
        PERSON_METADATA_FIELDS is guarded separately by test_person_metadata_fields_match_rust.
        """
        import json
        from pathlib import Path

        from posthog.hogql.property import PERSON_METADATA_FIELDS

        repo_root = Path(__file__).resolve().parents[3]
        taxonomy_path = repo_root / "frontend/src/taxonomy/core-filter-definitions-by-group.json"
        taxonomy = json.loads(taxonomy_path.read_text())
        taxonomy_keys = set(taxonomy.get("person_metadata", {}).keys())
        self.assertEqual(
            PERSON_METADATA_FIELDS,
            taxonomy_keys,
            "PERSON_METADATA_FIELDS in posthog/hogql/property.py must match the "
            "person_metadata group in core-filter-definitions-by-group.json. "
            "Update both, plus propertyDefinitionsModel.ts and the Rust injection.",
        )

    def test_person_metadata_fields_match_rust(self):
        """
        Guards Python ↔ Rust drift: asserts PERSON_METADATA_FIELDS matches the Rust slice in
        property_matching.rs. Without this, adding a field on the Python side (so it validates
        and saves) without updating Rust leaves the matcher's `_ => continue` arm skipping the
        field, so /flags/ evaluation silently matches nobody for it with no error.
        """
        import re
        from pathlib import Path

        from posthog.hogql.property import PERSON_METADATA_FIELDS

        repo_root = Path(__file__).resolve().parents[3]
        rust_src = (repo_root / "rust/feature-flags/src/properties/property_matching.rs").read_text()
        match = re.search(r"PERSON_METADATA_FIELDS:\s*&\[&str\]\s*=\s*&\[(.*?)\]", rust_src, re.S)
        assert match is not None, "could not find PERSON_METADATA_FIELDS in property_matching.rs"
        rust_fields = set(re.findall(r'"([^"]+)"', match.group(1)))
        self.assertEqual(
            PERSON_METADATA_FIELDS,
            rust_fields,
            "PERSON_METADATA_FIELDS in posthog/hogql/property.py must match the Rust slice in "
            "rust/feature-flags/src/properties/property_matching.rs. Update both, and add a match "
            "arm in flag_matching_utils::apply_person_cohort_to_state for any new field.",
        )

    def test_virtual_person_properties_on_person_scope(self):
        assert self._property_to_expr(
            {"type": "person", "key": "$virt_initial_channel_type", "value": "Organic Search"}, scope="person"
        ) == self._parse_expr("$virt_initial_channel_type = 'Organic Search'")

        assert self._property_to_expr(
            {"type": "person", "key": "$virt_mrr", "value": 100, "operator": "exact"}, scope="person"
        ) == self._parse_expr("$virt_mrr = 100")

    def test_virtual_group_properties_on_group_scope(self):
        assert self._property_to_expr(
            {
                "type": "group",
                "key": "$virt_mrr",
                "value": 100,
                "operator": "exact",
                "group_type_index": 0,
            },
            scope="group",
        ) == self._parse_expr("$virt_mrr = 100")

    def test_virtual_person_properties_on_event_scope(self):
        assert self._property_to_expr(
            {"type": "person", "key": "$virt_initial_channel_type", "value": "Organic Search"}, scope="event"
        ) == self._parse_expr("person.$virt_initial_channel_type = 'Organic Search'")
        assert self._property_to_expr(
            {"type": "person", "key": "$virt_revenue", "value": 100, "operator": "exact"}, scope="event"
        ) == self._parse_expr("person.$virt_revenue = 100")

    def test_virtual_group_properties_on_event_scope(self):
        assert self._property_to_expr(
            {"type": "group", "key": "$virt_revenue", "value": 100, "operator": "exact", "group_type_index": 0},
            scope="event",
        ) == self._parse_expr("group_0.$virt_revenue = 100")

    def test_map_virtual_properties(self):
        assert map_virtual_properties(
            ast.Field(chain=["person", "properties", "$virt_initial_channel_type"])
        ) == ast.Field(chain=["person", "$virt_initial_channel_type"])
        assert map_virtual_properties(ast.Field(chain=["person", "properties", "$virt_revenue"])) == ast.Field(
            chain=["person", "$virt_revenue"]
        )

        assert map_virtual_properties(ast.Field(chain=["properties", "$virt_initial_channel_type"])) == ast.Field(
            chain=["$virt_initial_channel_type"]
        )
        assert map_virtual_properties(ast.Field(chain=["properties", "$virt_revenue"])) == ast.Field(
            chain=["$virt_revenue"]
        )

        assert map_virtual_properties(ast.Field(chain=["person", "properties", "other property"])) == ast.Field(
            chain=["person", "properties", "other property"]
        )
        assert map_virtual_properties(ast.Field(chain=["properties", "other property"])) == ast.Field(
            chain=["properties", "other property"]
        )
        assert map_virtual_properties(ast.Field(chain=["person", "properties", 42])) == ast.Field(
            chain=["person", "properties", 42]
        )
        assert map_virtual_properties(ast.Field(chain=["properties", 42])) == ast.Field(chain=["properties", 42])

    @parameterized.expand(
        [
            (
                "traffic_type_bot",
                {"type": "event", "key": "$virt_traffic_type", "value": "Bot"},
                "$virt_traffic_type = 'Bot'",
            ),
            (
                "traffic_type_ai_agent",
                {"type": "event", "key": "$virt_traffic_type", "value": "AI Agent"},
                "$virt_traffic_type = 'AI Agent'",
            ),
            (
                "bot_name_googlebot",
                {"type": "event", "key": "$virt_bot_name", "value": "Googlebot"},
                "$virt_bot_name = 'Googlebot'",
            ),
        ]
    )
    def test_virtual_event_properties_on_event_scope(self, _name: str, prop_dict: dict, expected_expr: str):
        assert self._property_to_expr(prop_dict, scope="event") == self._parse_expr(expected_expr)

    @parameterized.expand(
        [
            (
                "is_not_bot",
                {"type": "event", "key": "$virt_traffic_type", "value": "Bot", "operator": "is_not"},
                "$virt_traffic_type != 'Bot'",
            ),
            (
                "icontains_google",
                {"type": "event", "key": "$virt_bot_name", "value": "Google", "operator": "icontains"},
                "toString($virt_bot_name) ilike '%Google%'",
            ),
            (
                "is_set",
                {"type": "event", "key": "$virt_traffic_type", "operator": "is_set"},
                "$virt_traffic_type != NULL",
            ),
        ]
    )
    def test_virtual_event_properties_with_operators(self, _name: str, prop_dict: dict, expected_expr: str):
        assert self._property_to_expr(prop_dict, scope="event") == self._parse_expr(expected_expr)

    def test_virtual_event_properties_boolean_filter(self):
        assert self._property_to_expr(
            {"type": "event", "key": "$virt_is_bot", "value": "true"}, scope="event"
        ) == self._parse_expr("$virt_is_bot = true")

        assert self._property_to_expr(
            {"type": "event", "key": "$virt_is_bot", "value": "false"}, scope="event"
        ) == self._parse_expr("$virt_is_bot = false")

    @parameterized.expand(
        [
            ("is_bot", "$virt_is_bot"),
            ("traffic_type", "$virt_traffic_type"),
            ("bot_name", "$virt_bot_name"),
            ("traffic_category", "$virt_traffic_category"),
        ]
    )
    def test_map_virtual_properties_for_event_properties(self, _name: str, virt_prop: str):
        assert map_virtual_properties(ast.Field(chain=["properties", virt_prop])) == ast.Field(chain=[virt_prop])

    def test_property_to_expr_event_metadata_group_scope_basic(self):
        assert self._property_to_expr(
            {"type": "event_metadata", "key": "$group_0", "operator": "exact", "value": "1234-abcd"},
            scope="group",
        ) == self._parse_expr("key = '1234-abcd' and index = 0")

    def test_property_to_expr_event_metadata_group_scope_list_single_value(self):
        assert self._property_to_expr(
            {"type": "event_metadata", "key": "$group_2", "operator": "exact", "value": ["1"]},
            scope="group",
        ) == self._parse_expr("key = '1' and index = 2")

    def test_property_to_expr_event_metadata_group_scope_invalid_key(self):
        with self.assertRaisesMessage(
            QueryError, "The 'event_metadata' property filter does not work in 'group' scope"
        ):
            self._property_to_expr(
                {"type": "event_metadata", "key": "$group_invalid", "operator": "exact", "value": "test"}, scope="group"
            )

    def test_property_to_expr_event_metadata_group_scope_multiple_values(self):
        with self.assertRaisesMessage(
            QueryError, "The '$group_3' property filter only supports one value in 'group' scope"
        ):
            self._property_to_expr(
                {"type": "event_metadata", "key": "$group_3", "operator": "exact", "value": ["1", "2"]}, scope="group"
            )

    def test_property_to_expr_between_operator(self):
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "age", "operator": "between", "value": [18, 65]}),
            self._parse_expr("(properties.age >= 18 AND properties.age <= 65)"),
        )

        self.assertEqual(
            self._property_to_expr({"type": "person", "key": "age", "operator": "between", "value": [25, 50]}),
            self._parse_expr("(person.properties.age >= 25 AND person.properties.age <= 50)"),
        )

        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "score", "operator": "not_between", "value": [0, 100]}),
            self._parse_expr("(properties.score < 0 OR properties.score > 100)"),
        )

    def test_property_to_expr_between_operator_validation(self):
        with self.assertRaisesMessage(QueryError, "between operator requires a two-element array [min, max]"):
            self._property_to_expr({"type": "event", "key": "age", "operator": "between", "value": 25})

        with self.assertRaisesMessage(QueryError, "between operator requires a two-element array [min, max]"):
            self._property_to_expr({"type": "event", "key": "age", "operator": "between", "value": [18]})

        with self.assertRaisesMessage(QueryError, "between operator requires a two-element array [min, max]"):
            self._property_to_expr({"type": "event", "key": "age", "operator": "between", "value": [18, 25, 65]})

        with self.assertRaisesMessage(QueryError, "not_between operator requires a two-element array [min, max]"):
            self._property_to_expr({"type": "event", "key": "age", "operator": "not_between", "value": 1})

        with self.assertRaisesMessage(
            QueryError, "between operator requires min value to be less than or equal to max value"
        ):
            self._property_to_expr({"type": "event", "key": "age", "operator": "between", "value": [10, 1]})

        with self.assertRaisesMessage(
            QueryError, "not_between operator requires min value to be less than or equal to max value"
        ):
            self._property_to_expr({"type": "event", "key": "age", "operator": "not_between", "value": [10, 1]})

        with self.assertRaisesMessage(QueryError, "between operator requires numeric values"):
            self._property_to_expr({"type": "event", "key": "age", "operator": "between", "value": ["abc", "def"]})

        with self.assertRaisesMessage(QueryError, "not_between operator requires numeric values"):
            self._property_to_expr({"type": "event", "key": "age", "operator": "not_between", "value": ["xyz", "123"]})

        with self.assertRaisesMessage(QueryError, "between operator requires numeric values"):
            self._property_to_expr({"type": "event", "key": "age", "operator": "between", "value": [None, 10]})

    @parameterized.expand(
        [
            ("trailing_backslash", "^abc\\"),
            ("unsupported_lookahead", "^foo(?!bar).+"),
            ("unbalanced_paren", "(unclosed"),
        ]
    )
    def test_property_to_expr_invalid_regex_raises_query_error(self, _name: str, bad_regex: str):
        # An invalid regex must surface as a user-facing QueryError, not crash the
        # whole query in ClickHouse with CANNOT_COMPILE_REGEXP.
        with self.assertRaisesMessage(QueryError, "Invalid regular expression"):
            self._property_to_expr({"type": "event", "key": "$ip", "value": bad_regex, "operator": "regex"})
        with self.assertRaisesMessage(QueryError, "Invalid regular expression"):
            self._property_to_expr({"type": "event", "key": "$ip", "value": bad_regex, "operator": "not_regex"})

    def test_property_to_expr_min_max_operators(self):
        # Test MIN operator (alias for GTE)
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "age", "operator": "min", "value": 18}),
            self._parse_expr("properties.age >= 18"),
        )

        # Test MAX operator (alias for LTE)
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "age", "operator": "max", "value": 65}),
            self._parse_expr("properties.age <= 65"),
        )

        # Test MIN with person properties
        self.assertEqual(
            self._property_to_expr({"type": "person", "key": "age", "operator": "min", "value": 25}),
            self._parse_expr("person.properties.age >= 25"),
        )

        # Test MAX with person properties
        self.assertEqual(
            self._property_to_expr({"type": "person", "key": "score", "operator": "max", "value": 100}),
            self._parse_expr("person.properties.score <= 100"),
        )

    def test_property_to_expr_semver_operators(self):
        # Every semver comparison is now gated on a strict-semver `match()` against the
        # property side so invalid values (leading zeros, wrong arity, etc.) are dropped
        # before the array comparison — see STRICT_SEMVER_REGEX in property.py for why.
        gate = "match(person.properties.app_version, '^\\\\s*v?(0|[1-9]\\\\d*)\\\\.(0|[1-9]\\\\d*)\\\\.(0|[1-9]\\\\d*)(?:[-+][^\\\\s]*)?\\\\s*$')"

        # Test semver_eq
        self.assertEqual(
            self._property_to_expr({"type": "person", "key": "app_version", "operator": "semver_eq", "value": "1.2.3"}),
            self._parse_expr(f"({gate} AND sortableSemver(person.properties.app_version) = sortableSemver('1.2.3'))"),
        )

        # Test semver_gt
        self.assertEqual(
            self._property_to_expr({"type": "person", "key": "app_version", "operator": "semver_gt", "value": "1.2.3"}),
            self._parse_expr(f"({gate} AND sortableSemver(person.properties.app_version) > sortableSemver('1.2.3'))"),
        )

        # Test semver_gte
        self.assertEqual(
            self._property_to_expr(
                {"type": "person", "key": "app_version", "operator": "semver_gte", "value": "1.2.3"}
            ),
            self._parse_expr(f"({gate} AND sortableSemver(person.properties.app_version) >= sortableSemver('1.2.3'))"),
        )

        # Test semver_lt
        self.assertEqual(
            self._property_to_expr({"type": "person", "key": "app_version", "operator": "semver_lt", "value": "1.2.3"}),
            self._parse_expr(f"({gate} AND sortableSemver(person.properties.app_version) < sortableSemver('1.2.3'))"),
        )

        # Test semver_lte
        self.assertEqual(
            self._property_to_expr(
                {"type": "person", "key": "app_version", "operator": "semver_lte", "value": "1.2.3"}
            ),
            self._parse_expr(f"({gate} AND sortableSemver(person.properties.app_version) <= sortableSemver('1.2.3'))"),
        )

        # Test semver_tilde (~1.2.3 means >=1.2.3 <1.3.0)
        self.assertEqual(
            self._property_to_expr(
                {"type": "person", "key": "app_version", "operator": "semver_tilde", "value": "1.2.3"}
            ),
            self._parse_expr(
                f"({gate} AND sortableSemver(person.properties.app_version) >= sortableSemver('1.2.3') AND sortableSemver(person.properties.app_version) < sortableSemver('1.3.0'))"
            ),
        )

        # Test semver_caret (^1.2.3 means >=1.2.3 <2.0.0)
        self.assertEqual(
            self._property_to_expr(
                {"type": "person", "key": "app_version", "operator": "semver_caret", "value": "1.2.3"}
            ),
            self._parse_expr(
                f"({gate} AND sortableSemver(person.properties.app_version) >= sortableSemver('1.2.3') AND sortableSemver(person.properties.app_version) < sortableSemver('2.0.0'))"
            ),
        )

        # Test semver_caret with 0.x.y versions (^0.2.3 means >=0.2.3 <0.3.0)
        self.assertEqual(
            self._property_to_expr(
                {"type": "person", "key": "app_version", "operator": "semver_caret", "value": "0.2.3"}
            ),
            self._parse_expr(
                f"({gate} AND sortableSemver(person.properties.app_version) >= sortableSemver('0.2.3') AND sortableSemver(person.properties.app_version) < sortableSemver('0.3.0'))"
            ),
        )

        # Test semver_caret with 0.0.x versions (^0.0.3 means >=0.0.3 <0.0.4)
        self.assertEqual(
            self._property_to_expr(
                {"type": "person", "key": "app_version", "operator": "semver_caret", "value": "0.0.3"}
            ),
            self._parse_expr(
                f"({gate} AND sortableSemver(person.properties.app_version) >= sortableSemver('0.0.3') AND sortableSemver(person.properties.app_version) < sortableSemver('0.0.4'))"
            ),
        )

        # Test semver_wildcard (1.2.* means >=1.2.0 <1.3.0)
        self.assertEqual(
            self._property_to_expr(
                {"type": "person", "key": "app_version", "operator": "semver_wildcard", "value": "1.2.*"}
            ),
            self._parse_expr(
                f"({gate} AND sortableSemver(person.properties.app_version) >= sortableSemver('1.2.0') AND sortableSemver(person.properties.app_version) < sortableSemver('1.3.0'))"
            ),
        )

        # Test semver_wildcard with major version (1.* means >=1.0.0 <2.0.0)
        self.assertEqual(
            self._property_to_expr(
                {"type": "person", "key": "app_version", "operator": "semver_wildcard", "value": "1.*"}
            ),
            self._parse_expr(
                f"({gate} AND sortableSemver(person.properties.app_version) >= sortableSemver('1.0.0') AND sortableSemver(person.properties.app_version) < sortableSemver('2.0.0'))"
            ),
        )

    def test_property_to_expr_semver_validation(self):
        version_gate = "match(person.properties.version, '^\\\\s*v?(0|[1-9]\\\\d*)\\\\.(0|[1-9]\\\\d*)\\\\.(0|[1-9]\\\\d*)(?:[-+][^\\\\s]*)?\\\\s*$')"

        # Test tilde with bare major (~1 means >=1.0.0 <2.0.0)
        self.assertEqual(
            self._property_to_expr({"type": "person", "key": "version", "operator": "semver_tilde", "value": "1"}),
            self._parse_expr(
                f"({version_gate} AND sortableSemver(person.properties.version) >= sortableSemver('1.0.0') AND sortableSemver(person.properties.version) < sortableSemver('2.0.0'))"
            ),
        )

        # Test caret requires valid semver
        with self.assertRaisesMessage(QueryError, "Caret operator requires a valid semver string"):
            self._property_to_expr({"type": "person", "key": "version", "operator": "semver_caret", "value": "abc.def"})

        # Test wildcard requires valid pattern
        with self.assertRaisesMessage(QueryError, "Wildcard operator requires a valid semver string (e.g., '1.2.3')"):
            self._property_to_expr({"type": "person", "key": "version", "operator": "semver_wildcard", "value": "*"})

        # Test wildcard requires valid pattern
        with self.assertRaisesMessage(QueryError, "Wildcard operator requires a valid semver string (e.g., '1.2.3')"):
            self._property_to_expr({"type": "person", "key": "version", "operator": "semver_wildcard", "value": ".*"})

    def test_property_to_expr_semver_edge_cases(self):
        """Test edge cases to document expected behavior with various version formats.

        The property side is always gated on STRICT_SEMVER_REGEX (see property.py); the
        filter side passes through to sortableSemver verbatim. So a filter value like
        '01.02.03' or 'v1.2.3' is preserved as-is in the AST — the gate is only applied
        to the property side, where invalid stored values would otherwise leak through."""
        gate = "match(person.properties.app_version, '^\\\\s*v?(0|[1-9]\\\\d*)\\\\.(0|[1-9]\\\\d*)\\\\.(0|[1-9]\\\\d*)(?:[-+][^\\\\s]*)?\\\\s*$')"
        version_gate = "match(person.properties.version, '^\\\\s*v?(0|[1-9]\\\\d*)\\\\.(0|[1-9]\\\\d*)\\\\.(0|[1-9]\\\\d*)(?:[-+][^\\\\s]*)?\\\\s*$')"

        # Minimal version (0.0.0)
        self.assertEqual(
            self._property_to_expr({"type": "person", "key": "app_version", "operator": "semver_eq", "value": "0.0.0"}),
            self._parse_expr(f"({gate} AND sortableSemver(person.properties.app_version) = sortableSemver('0.0.0'))"),
        )

        # Prerelease versions (1.2.3-alpha) - filter passes through verbatim
        self.assertEqual(
            self._property_to_expr(
                {"type": "person", "key": "app_version", "operator": "semver_eq", "value": "1.2.3-alpha"}
            ),
            self._parse_expr(
                f"({gate} AND sortableSemver(person.properties.app_version) = sortableSemver('1.2.3-alpha'))"
            ),
        )

        # v-prefix (v1.2.3) - filter passes through verbatim
        self.assertEqual(
            self._property_to_expr(
                {"type": "person", "key": "app_version", "operator": "semver_eq", "value": "v1.2.3"}
            ),
            self._parse_expr(f"({gate} AND sortableSemver(person.properties.app_version) = sortableSemver('v1.2.3'))"),
        )

        # Leading space ( 1.2.3) - filter passes through verbatim
        self.assertEqual(
            self._property_to_expr(
                {"type": "person", "key": "app_version", "operator": "semver_eq", "value": " 1.2.3"}
            ),
            self._parse_expr(f"({gate} AND sortableSemver(person.properties.app_version) = sortableSemver(' 1.2.3'))"),
        )

        # Trailing space (1.2.3 ) - filter passes through verbatim
        self.assertEqual(
            self._property_to_expr(
                {"type": "person", "key": "app_version", "operator": "semver_eq", "value": "1.2.3 "}
            ),
            self._parse_expr(f"({gate} AND sortableSemver(person.properties.app_version) = sortableSemver('1.2.3 '))"),
        )

        # Leading zeros (01.02.03) in the *filter* side pass through verbatim. The
        # match gate is only on the *property* side, so invalid filter inputs still
        # reach sortableSemver and trigger ClickHouse's array NULL ordering — the
        # net effect is that no rows match (since no valid prop equals an invalid
        # parsed filter), which is the desired safety behavior.
        self.assertEqual(
            self._property_to_expr(
                {"type": "person", "key": "app_version", "operator": "semver_eq", "value": "01.02.03"}
            ),
            self._parse_expr(
                f"({gate} AND sortableSemver(person.properties.app_version) = sortableSemver('01.02.03'))"
            ),
        )

        # Too many version numbers (1.2.3.4) - Common in .NET, passes through verbatim on filter side
        self.assertEqual(
            self._property_to_expr(
                {"type": "person", "key": "app_version", "operator": "semver_eq", "value": "1.2.3.4"}
            ),
            self._parse_expr(f"({gate} AND sortableSemver(person.properties.app_version) = sortableSemver('1.2.3.4'))"),
        )

        # Empty component (1..2.3) - filter passes through verbatim
        self.assertEqual(
            self._property_to_expr(
                {"type": "person", "key": "app_version", "operator": "semver_eq", "value": "1..2.3"}
            ),
            self._parse_expr(f"({gate} AND sortableSemver(person.properties.app_version) = sortableSemver('1..2.3'))"),
        )

        # Trailing dot (1.2.3.) - filter passes through verbatim
        self.assertEqual(
            self._property_to_expr(
                {"type": "person", "key": "app_version", "operator": "semver_eq", "value": "1.2.3."}
            ),
            self._parse_expr(f"({gate} AND sortableSemver(person.properties.app_version) = sortableSemver('1.2.3.'))"),
        )

        # Leading dot (.1.2.3) - filter passes through verbatim
        self.assertEqual(
            self._property_to_expr(
                {"type": "person", "key": "app_version", "operator": "semver_eq", "value": ".1.2.3"}
            ),
            self._parse_expr(f"({gate} AND sortableSemver(person.properties.app_version) = sortableSemver('.1.2.3'))"),
        )

        # Negative version part (1.-2.3) - filter passes through verbatim
        self.assertEqual(
            self._property_to_expr(
                {"type": "person", "key": "app_version", "operator": "semver_eq", "value": "1.-2.3"}
            ),
            self._parse_expr(f"({gate} AND sortableSemver(person.properties.app_version) = sortableSemver('1.-2.3'))"),
        )

        # Tilde with bare major zero (~0 means >=0.0.0 <1.0.0)
        self.assertEqual(
            self._property_to_expr({"type": "person", "key": "version", "operator": "semver_tilde", "value": "0"}),
            self._parse_expr(
                f"({version_gate} AND sortableSemver(person.properties.version) >= sortableSemver('0.0.0') AND sortableSemver(person.properties.version) < sortableSemver('1.0.0'))"
            ),
        )

        # Caret with leading zeros on the filter side passes through; the match gate
        # on the property side keeps only strict-semver property values.
        self.assertEqual(
            self._property_to_expr(
                {"type": "person", "key": "app_version", "operator": "semver_caret", "value": "01.02.03"}
            ),
            self._parse_expr(
                f"({gate} AND sortableSemver(person.properties.app_version) >= sortableSemver('01.02.03') AND sortableSemver(person.properties.app_version) < sortableSemver('2.0.0'))"
            ),
        )

        # Wildcard with too many parts (1.2.3.*) - bounds passed through verbatim on filter side
        self.assertEqual(
            self._property_to_expr(
                {"type": "person", "key": "app_version", "operator": "semver_wildcard", "value": "1.2.3.*"}
            ),
            self._parse_expr(
                f"({gate} AND sortableSemver(person.properties.app_version) >= sortableSemver('1.2.3.0') AND sortableSemver(person.properties.app_version) < sortableSemver('1.2.4.0'))"
            ),
        )

    # -- Operator coverage: every PropertyOperator must be handled by property_to_expr --

    # Test values appropriate for each operator type
    OPERATOR_TEST_VALUES: dict[PropertyOperator, Any] = {
        PropertyOperator.IS_SET: "",
        PropertyOperator.IS_NOT_SET: "",
        PropertyOperator.BETWEEN: [1, 10],
        PropertyOperator.NOT_BETWEEN: [1, 10],
        PropertyOperator.IN_: ["a", "b"],
        PropertyOperator.NOT_IN: ["a", "b"],
        PropertyOperator.SEMVER_EQ: "1.2.3",
        PropertyOperator.SEMVER_NEQ: "1.2.3",
        PropertyOperator.SEMVER_GT: "1.2.3",
        PropertyOperator.SEMVER_GTE: "1.2.3",
        PropertyOperator.SEMVER_LT: "1.2.3",
        PropertyOperator.SEMVER_LTE: "1.2.3",
        PropertyOperator.SEMVER_TILDE: "1.2.3",
        PropertyOperator.SEMVER_CARET: "1.2.3",
        PropertyOperator.SEMVER_WILDCARD: "1.*",
        PropertyOperator.ICONTAINS_MULTI: ["a", "b"],
        PropertyOperator.NOT_ICONTAINS_MULTI: ["a", "b"],
    }

    # FLAG_EVALUATES_TO is dispatched via FlagPropertyFilter, not _expr_to_compare_op
    @parameterized.expand([(op.value,) for op in PropertyOperator if op not in {PropertyOperator.FLAG_EVALUATES_TO}])
    def test_operator_coverage(self, operator_value: str):
        value = self.OPERATOR_TEST_VALUES.get(PropertyOperator(operator_value), "test_value")
        result = self._property_to_expr(
            {"type": "event", "key": "test_prop", "value": value, "operator": operator_value}
        )
        self.assertIsInstance(result, ast.Expr)

    def test_flag_evaluates_to_produces_neutral_expr(self):
        prop = FlagPropertyFilter(type="flag", key="my-flag", value="true", operator="flag_evaluates_to")
        result = property_to_expr([prop], self.team)
        self.assertEqual(result, ast.Constant(value=1))

    # Flag dependency conditions also arrive as plain dicts (e.g. via the user blast radius API),
    # taking the legacy Property path instead of FlagPropertyFilter
    @parameterized.expand([("enabled", True), ("disabled", False), ("variant", "control")])
    def test_flag_dependency_dict_produces_neutral_expr(self, _name: str, value: Any):
        result = self._property_to_expr({"type": "flag", "key": "123", "value": value, "operator": "flag_evaluates_to"})
        self.assertEqual(result, ast.Constant(value=1))

    def test_flag_dependency_combined_with_person_property(self):
        flag_prop: dict[str, Any] = {"type": "flag", "key": "123", "value": False, "operator": "flag_evaluates_to"}
        result = self._property_to_expr(
            PropertyGroup(
                type=PropertyOperatorType.AND,
                values=[
                    Property(**flag_prop),
                    Property(type="person", key="email", value="hog@posthog.com", operator="exact"),
                ],
            ),
            scope="person",
        )
        self.assertIsInstance(result, ast.And)
        self.assertEqual(cast(ast.And, result).exprs[0], ast.Constant(value=1))
        # The person filter must survive as a real comparison, not collapse to neutral too
        self.assertIsInstance(cast(ast.And, result).exprs[1], ast.CompareOperation)


class TestPropertyIsSetIsNotSetWithData(APIBaseTest):
    # Sentinel to indicate a property should not be included in the event
    NOT_SET: Any = object()

    # Expected is_set value can be True, False, or a callable(is_materialized) -> bool
    # When materialized, empty string and "null" string become NULL due to nullIf wrapping
    # (this is a long-standing bug, and it's ok to change these tests if you fix it!)
    ONLY_WHEN_NOT_MATERIALIZED = staticmethod(lambda m: not m)

    def setUp(self):
        super().setUp()
        self.event_name = "test_is_set_event"

        # (property_name, value, property_type, expected_is_set)
        # expected_is_set: True, False, or callable(is_materialized) -> bool
        self.test_cases: list[tuple[str, Any, PropertyType, Any]] = [
            # String type: value, empty, "null" literal, null, not set
            ("string_value_prop", "hello", PropertyType.String, True),
            ("string_empty_prop", "", PropertyType.String, self.ONLY_WHEN_NOT_MATERIALIZED),
            ("string_null_literal_prop", "null", PropertyType.String, self.ONLY_WHEN_NOT_MATERIALIZED),
            ("string_null_prop", None, PropertyType.String, False),
            ("string_not_set_prop", self.NOT_SET, PropertyType.String, False),
            # Numeric type: zero, non-zero int, non-zero float, string values, null, not set
            # Type coercion converts invalid strings to NULL
            ("numeric_zero_prop", 0, PropertyType.Numeric, True),
            ("numeric_int_prop", 42, PropertyType.Numeric, True),
            ("numeric_float_prop", 3.14, PropertyType.Numeric, True),
            ("numeric_string_valid_prop", "42", PropertyType.Numeric, True),
            ("numeric_string_invalid_prop", "invalid_number", PropertyType.Numeric, False),
            ("numeric_string_empty_prop", "", PropertyType.Numeric, False),
            ("numeric_null_prop", None, PropertyType.Numeric, False),
            ("numeric_not_set_prop", self.NOT_SET, PropertyType.Numeric, False),
            # Boolean type: true, false, string variants, invalid, null, not set
            # Only lowercase "true"/"false" strings are recognized
            ("bool_true_prop", True, PropertyType.Boolean, True),
            ("bool_false_prop", False, PropertyType.Boolean, True),
            ("bool_string_true_lower_prop", "true", PropertyType.Boolean, True),
            ("bool_string_true_title_prop", "True", PropertyType.Boolean, False),
            ("bool_string_true_upper_prop", "TRUE", PropertyType.Boolean, False),
            ("bool_string_false_lower_prop", "false", PropertyType.Boolean, True),
            ("bool_string_invalid_prop", "invalid_bool", PropertyType.Boolean, False),
            ("bool_string_empty_prop", "", PropertyType.Boolean, False),
            ("bool_null_prop", None, PropertyType.Boolean, False),
            ("bool_not_set_prop", self.NOT_SET, PropertyType.Boolean, False),
        ]

        # Create PropertyDefinitions for each property
        for prop_name, _, prop_type, _ in self.test_cases:
            PropertyDefinition.objects.create(
                team=self.team,
                name=prop_name,
                type=PropertyDefinition.Type.EVENT,
                property_type=prop_type,
            )

        # Create a single event with all properties (except NOT_SET ones)
        properties = {prop_name: value for prop_name, value, _, _ in self.test_cases if value is not self.NOT_SET}

        _create_event(
            team=self.team,
            event=self.event_name,
            distinct_id="test_user",
            properties=properties,
        )

    def _expected_is_set_values(self, is_materialized: bool) -> dict[str, int]:
        result = {}
        for prop_name, _, _, expected in self.test_cases:
            if callable(expected):
                result[prop_name] = 1 if expected(is_materialized) else 0
            else:
                result[prop_name] = 1 if expected else 0
        return result

    def _expected_is_not_set_values(self, is_materialized: bool) -> dict[str, int]:
        return {k: 1 - v for k, v in self._expected_is_set_values(is_materialized).items()}

    @parameterized.expand([("not_materialized", False), ("materialized", True)])
    def test_is_set_operator(self, _name: str, is_materialized: bool):
        if is_materialized:
            self.addCleanup(cleanup_materialized_columns)
            for prop_name, _, _, _ in self.test_cases:
                materialize("events", prop_name)

        select_exprs: list[ast.Expr] = [
            ast.Alias(
                alias=prop_name,
                expr=property_to_expr(
                    {"type": "event", "key": prop_name, "operator": "is_set"},
                    team=self.team,
                    scope="event",
                ),
            )
            for prop_name, _, _, _ in self.test_cases
        ]

        query_ast = ast.SelectQuery(
            select=select_exprs,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value=self.event_name),
            ),
        )

        result = execute_hogql_query(team=self.team, query=query_ast)
        assert result.columns
        row: Iterable[Any] = result.results[0]
        assert row
        results = dict(zip(result.columns, row))

        assert results == self._expected_is_set_values(is_materialized)

    @parameterized.expand([("not_materialized", False), ("materialized", True)])
    def test_is_not_set_operator(self, _name: str, is_materialized: bool):
        if is_materialized:
            self.addCleanup(cleanup_materialized_columns)
            for prop_name, _, _, _ in self.test_cases:
                materialize("events", prop_name)

        select_exprs: list[ast.Expr] = [
            ast.Alias(
                alias=prop_name,
                expr=property_to_expr(
                    {"type": "event", "key": prop_name, "operator": "is_not_set"},
                    team=self.team,
                    scope="event",
                ),
            )
            for prop_name, _, _, _ in self.test_cases
        ]

        query_ast = ast.SelectQuery(
            select=select_exprs,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value=self.event_name),
            ),
        )

        result = execute_hogql_query(team=self.team, query=query_ast)
        assert result.columns
        row: Iterable[Any] = result.results[0]
        assert row
        results = dict(zip(result.columns, row))

        assert results == self._expected_is_not_set_values(is_materialized)


class TestPropertyDateOperatorsWithData(APIBaseTest):
    """End-to-end tests for IS_DATE_* operators that actually execute the generated SQL.

    Unit tests only assert AST shape, which cannot catch cases where the rendered
    ClickHouse SQL is syntactically valid but rejected at runtime. In particular,
    PropertySwapper wraps DateTime-typed properties with ``parseDateTime64BestEffortOrNull``,
    and our outer ``toDateTime`` wrap must not produce a nested parse on a DateTime64
    column — ``parseDateTime64BestEffortOrNull`` only accepts String input.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        PropertyDefinition.objects.create(
            team=cls.team,
            name="signup_dt",
            type=PropertyDefinition.Type.EVENT,
            property_type=PropertyType.Datetime,
        )
        _create_event(
            team=cls.team,
            event="signup",
            distinct_id="u1",
            properties={"signup_dt": "2026-03-19T10:00:00Z"},
        )
        _create_event(
            team=cls.team,
            event="signup",
            distinct_id="u2",
            properties={"signup_dt": "2026-03-19T18:00:00Z"},
        )

    def _run(self, filter: dict) -> int:
        expr = property_to_expr(filter, team=self.team, scope="event")
        query_ast = ast.SelectQuery(
            select=[ast.Call(name="count", args=[])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(
                exprs=[
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["event"]),
                        right=ast.Constant(value="signup"),
                    ),
                    expr,
                ]
            ),
        )
        result = execute_hogql_query(team=self.team, query=query_ast)
        return result.results[0][0]

    @parameterized.expand(
        [
            ("is_date_before_iso_z", "2026-03-19T14:00:00Z", "is_date_before", 1),
            ("is_date_before_mysql", "2026-03-19 14:00:00", "is_date_before", 1),
            ("is_date_after_iso_z", "2026-03-19T14:00:00Z", "is_date_after", 1),
            ("is_date_after_mysql", "2026-03-19 14:00:00", "is_date_after", 1),
            ("is_date_before_date_only", "2026-03-20", "is_date_before", 2),
            ("is_date_after_date_only", "2026-03-18", "is_date_after", 2),
        ]
    )
    def test_is_date_operator_on_datetime_event_property(
        self, _name: str, value: str, operator: str, expected_count: int
    ):
        count = self._run({"type": "event", "key": "signup_dt", "value": value, "operator": operator})
        assert count == expected_count

    @parameterized.expand(
        [
            # Events stored: u1 = 2026-03-19T10:00:00Z (03:00 PDT), u2 = 2026-03-19T18:00:00Z (11:00 PDT).
            #
            # ISO-with-Z filters carry an absolute offset and must resolve to the same moment
            # regardless of team timezone. This is the regression guard for the silent-drift bug
            # where stripping the Z would have silently re-interpreted the RHS in team time.
            ("la_is_date_before_iso_z", "2026-03-19T14:00:00Z", "is_date_before", 1),
            ("la_is_date_after_iso_z", "2026-03-19T14:00:00Z", "is_date_after", 1),
            # Naive MySQL-format filters are deliberately interpreted as team-local wall clock.
            # 07:00 PDT = 14:00 UTC, so the same event split as the UTC case above.
            ("la_is_date_before_mysql_local", "2026-03-19 07:00:00", "is_date_before", 1),
            ("la_is_date_after_mysql_local", "2026-03-19 07:00:00", "is_date_after", 1),
            # 14:00 PDT = 21:00 UTC, past both events.
            ("la_is_date_before_mysql_late", "2026-03-19 14:00:00", "is_date_before", 2),
            ("la_is_date_after_mysql_late", "2026-03-19 14:00:00", "is_date_after", 0),
            # Date-only filters are midnight team-local: 2026-03-20 00:00 PDT = 2026-03-20 07:00 UTC.
            ("la_is_date_before_date_only", "2026-03-20", "is_date_before", 2),
            ("la_is_date_after_date_only", "2026-03-18", "is_date_after", 2),
        ]
    )
    def test_is_date_operator_on_datetime_event_property_non_utc_team(
        self, _name: str, value: str, operator: str, expected_count: int
    ):
        self.team.timezone = "America/Los_Angeles"
        self.team.save(update_fields=["timezone"])

        count = self._run({"type": "event", "key": "signup_dt", "value": value, "operator": operator})
        assert count == expected_count
