from typing import Union, cast, Optional, Any, Literal
from unittest.mock import MagicMock, patch

from posthog.constants import PropertyOperatorType, TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import (
    has_aggregation,
    property_to_expr,
    selector_to_expr,
    tag_name_to_expr,
    entity_to_expr,
    map_virtual_properties,
)
from posthog.hogql.visitor import clear_locations
from posthog.models import (
    Cohort,
    Property,
    PropertyDefinition,
    Team,
)
from posthog.models.property import PropertyGroup
from posthog.models.property_definition import PropertyType
from posthog.schema import HogQLPropertyFilter, RetentionEntity, EmptyPropertyFilter
from posthog.test.base import BaseTest
from posthog.warehouse.models import DataWarehouseTable, DataWarehouseJoin, DataWarehouseCredential

elements_chain_match = lambda x: parse_expr("elements_chain =~ {regex}", {"regex": ast.Constant(value=str(x))})
elements_chain_imatch = lambda x: parse_expr("elements_chain =~* {regex}", {"regex": ast.Constant(value=str(x))})
not_call = lambda x: ast.Call(name="not", args=[x])


class TestProperty(BaseTest):
    maxDiff = None

    def _property_to_expr(
        self,
        property: Union[PropertyGroup, Property, HogQLPropertyFilter, dict, list],
        team: Optional[Team] = None,
        scope: Optional[Literal["event", "person", "group"]] = None,
    ):
        return clear_locations(property_to_expr(property, team=team or self.team, scope=scope or "event"))

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
            self._parse_expr("group_0.properties.a = NULL OR (NOT JSONHas(group_0.properties, 'a'))"),
            self._property_to_expr(
                {"type": "group", "group_type_index": 0, "key": "a", "value": "b", "operator": "is_not_set"}
            ),
        )
        self.assertEqual(
            self._property_to_expr(Property(type="group", group_type_index=0, key="a", value=["b", "c"])),
            self._parse_expr("group_0.properties.a in ('b', 'c')"),
        )

        self.assertEqual(self._property_to_expr({"type": "group", "key": "a", "value": "b"}), self._parse_expr("1"))

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
            self._parse_expr("properties.a = NULL OR (NOT JSONHas(properties, 'a'))"),
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
            self._parse_expr("ifNull(match(properties.a, '.*'), 0)"),
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
            self._property_to_expr({"type": "event", "key": "a", "operator": "icontains"}),  # value missing
        )
        self.assertEqual(
            self._parse_expr("1"),
            self._property_to_expr({}),  # incomplete event
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
            self._parse_expr("toString(properties.a) ilike '%b%' or toString(properties.a) ilike '%c%'"),
        )
        a = self._property_to_expr({"type": "event", "key": "a", "value": ["b", "c"], "operator": "regex"})
        self.assertEqual(
            a,
            self._parse_expr("ifNull(match(properties.a, 'b'), 0) or ifNull(match(properties.a, 'c'), 0)"),
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
            self._parse_expr("toString(properties.a) not ilike '%b%' and toString(properties.a) not ilike '%c%'"),
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
            self._parse_expr("arrayExists(text -> ifNull(match(text, 'text-text.'), 0), elements_chain_texts)"),
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

    def test_entity_to_expr_actions_type_with_id(self):
        action_mock = MagicMock()
        with patch("posthog.models.Action.objects.get", return_value=action_mock):
            entity = RetentionEntity(**{"type": TREND_FILTER_TYPE_ACTIONS, "id": 123})
            result = entity_to_expr(entity, self.team)
            self.assertIsInstance(result, ast.Expr)

    def test_entity_to_expr_events_type_with_id(self):
        entity = RetentionEntity(**{"type": TREND_FILTER_TYPE_EVENTS, "id": "event_id"})
        result = entity_to_expr(entity, self.team)
        expected = ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["events", "event"]),
                    right=ast.Constant(value="event_id"),
                )
            ]
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

    def test_virtual_person_properties_on_person_scope(self):
        assert self._property_to_expr(
            {"type": "person", "key": "$virt_initial_channel_type", "value": "Organic Search"}, scope="person"
        ) == self._parse_expr("$virt_initial_channel_type = 'Organic Search'")

        assert self._property_to_expr(
            {"type": "person", "key": "$virt_revenue_last_30_days", "value": 100, "operator": "exact"}, scope="person"
        ) == self._parse_expr("$virt_revenue_last_30_days = 100")

    def test_virtual_person_properties_on_event_scope(self):
        assert self._property_to_expr(
            {"type": "person", "key": "$virt_initial_channel_type", "value": "Organic Search"}, scope="event"
        ) == self._parse_expr("person.$virt_initial_channel_type = 'Organic Search'")
        assert self._property_to_expr(
            {"type": "person", "key": "$virt_revenue", "value": 100, "operator": "exact"}, scope="event"
        ) == self._parse_expr("person.$virt_revenue = 100")

    def test_map_virtual_properties(self):
        assert map_virtual_properties(
            ast.Field(chain=["person", "properties", "$virt_initial_channel_type"])
        ) == ast.Field(chain=["person", "$virt_initial_channel_type"])
        assert map_virtual_properties(ast.Field(chain=["properties", "$virt_initial_channel_type"])) == ast.Field(
            chain=["$virt_initial_channel_type"]
        )
        assert map_virtual_properties(ast.Field(chain=["person", "properties", "$virt_revenue"])) == ast.Field(
            chain=["person", "$virt_revenue"]
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
