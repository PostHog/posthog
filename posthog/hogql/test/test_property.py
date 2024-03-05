from typing import List, Union, cast, Optional, Dict, Any, Literal
from unittest.mock import MagicMock, patch

from posthog.constants import PropertyOperatorType, TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import (
    action_to_expr,
    element_chain_key_filter,
    has_aggregation,
    property_to_expr,
    selector_to_expr,
    tag_name_to_expr,
    entity_to_expr,
)
from posthog.hogql.visitor import clear_locations
from posthog.models import (
    Action,
    ActionStep,
    Cohort,
    Property,
    PropertyDefinition,
    Team,
)
from posthog.models.property import PropertyGroup
from posthog.models.property_definition import PropertyType
from posthog.schema import HogQLPropertyFilter, PropertyOperator, RetentionEntity
from posthog.test.base import BaseTest

elements_chain_match = lambda x: parse_expr("elements_chain =~ {regex}", {"regex": ast.Constant(value=str(x))})
elements_chain_imatch = lambda x: parse_expr("elements_chain =~* {regex}", {"regex": ast.Constant(value=str(x))})
not_call = lambda x: ast.Call(name="not", args=[x])


class TestProperty(BaseTest):
    maxDiff = None

    def _property_to_expr(
        self,
        property: Union[PropertyGroup, Property, dict, list],
        team: Optional[Team] = None,
        scope: Optional[Literal["event", "person"]] = None,
    ):
        return clear_locations(property_to_expr(property, team=team or self.team, scope=scope or "event"))

    def _selector_to_expr(self, selector: str):
        return clear_locations(selector_to_expr(selector))

    def _parse_expr(self, expr: str, placeholders: Dict[str, Any] = None):
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
            self._parse_expr("group_0.properties.a = 'b' OR group_0.properties.a = 'c'"),
        )

        with self.assertRaises(Exception) as e:
            self._property_to_expr({"type": "group", "key": "a", "value": "b"})
        self.assertEqual(
            str(e.exception),
            "Missing required attr group_type_index for property type group with key a",
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
            self._parse_expr("properties.a ilike '%3%'"),
        )
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "a", "value": "3", "operator": "not_icontains"}),
            self._parse_expr("properties.a not ilike '%3%'"),
        )
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "a", "value": ".*", "operator": "regex"}),
            self._parse_expr("ifNull(match(properties.a, '.*'), false)"),
        )
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "a", "value": ".*", "operator": "not_regex"}),
            self._parse_expr("ifNull(not(match(properties.a, '.*')), true)"),
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
                {"type": "event", "key": "unknown_prop", "value": "true"},
                team=self.team,
            ),
            self._parse_expr("properties.unknown_prop = true"),
        )
        self.assertEqual(
            self._property_to_expr(
                {"type": "event", "key": "boolean_prop", "value": "false"},
                team=self.team,
            ),
            self._parse_expr("properties.boolean_prop = false"),
        )

    def test_property_to_expr_event_list(self):
        # positive
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "a", "value": ["b", "c"], "operator": "exact"}),
            self._parse_expr("properties.a = 'b' OR properties.a = 'c'"),
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
            self._parse_expr("properties.a ilike '%b%' or properties.a ilike '%c%'"),
        )
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "a", "value": ["b", "c"], "operator": "regex"}),
            self._parse_expr("ifNull(match(properties.a, 'b'), false) or ifNull(match(properties.a, 'c'), false)"),
        )
        # negative
        self.assertEqual(
            self._property_to_expr({"type": "event", "key": "a", "value": ["b", "c"], "operator": "is_not"}),
            self._parse_expr("properties.a != 'b' AND properties.a != 'c'"),
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
            self._parse_expr("properties.a not ilike '%b%' and properties.a not ilike '%c%'"),
        )
        self.assertEqual(
            self._property_to_expr(
                {
                    "type": "event",
                    "key": "a",
                    "value": ["b", "c"],
                    "operator": "not_regex",
                }
            ),
            self._parse_expr(
                "ifNull(not(match(properties.a, 'b')), true) and ifNull(not(match(properties.a, 'c')), true)"
            ),
        )

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
            clear_locations(element_chain_key_filter("href", "href-text.", PropertyOperator.exact)),
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
            clear_locations(element_chain_key_filter("text", "text-text.", PropertyOperator.regex)),
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
                        Union[List[Property], List[PropertyGroup]],
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
            clear_locations(elements_chain_match('div([-_a-zA-Z0-9\\.:"= ]*?)?($|;|:([^;^\\s]*(;|$|\\s)))')),
        )
        self.assertEqual(
            self._selector_to_expr("div > div"),
            clear_locations(
                elements_chain_match(
                    'div([-_a-zA-Z0-9\\.:"= ]*?)?($|;|:([^;^\\s]*(;|$|\\s)))div([-_a-zA-Z0-9\\.:"= ]*?)?($|;|:([^;^\\s]*(;|$|\\s))).*'
                )
            ),
        )
        self.assertEqual(
            self._selector_to_expr("a[href='boo']"),
            clear_locations(
                elements_chain_match('a.*?href="boo".*?([-_a-zA-Z0-9\\.:"= ]*?)?($|;|:([^;^\\s]*(;|$|\\s)))')
            ),
        )
        self.assertEqual(
            self._selector_to_expr(".class"),
            clear_locations(elements_chain_match('.*?\\.class([-_a-zA-Z0-9\\.:"= ]*?)?($|;|:([^;^\\s]*(;|$|\\s)))')),
        )
        self.assertEqual(
            self._selector_to_expr("#withid"),
            clear_locations(
                elements_chain_match('.*?attr_id="withid".*?([-_a-zA-Z0-9\\.:"= ]*?)?($|;|:([^;^\\s]*(;|$|\\s)))')
            ),
        )
        self.assertEqual(
            self._selector_to_expr("#with-dashed-id"),
            clear_locations(
                elements_chain_match(
                    '.*?attr_id="with\\-dashed\\-id".*?([-_a-zA-Z0-9\\.:"= ]*?)?($|;|:([^;^\\s]*(;|$|\\s)))'
                )
            ),
        )
        self.assertEqual(
            self._selector_to_expr("#with-dashed-id"),
            self._selector_to_expr("[id='with-dashed-id']"),
        )
        self.assertEqual(
            self._selector_to_expr("#with\\slashed\\id"),
            clear_locations(
                elements_chain_match(
                    '.*?attr_id="with\\\\slashed\\\\id".*?([-_a-zA-Z0-9\\.:"= ]*?)?($|;|:([^;^\\s]*(;|$|\\s)))'
                )
            ),
        )

    def test_elements_chain_key_filter(self):
        self.assertEqual(
            clear_locations(element_chain_key_filter("href", "boo..", PropertyOperator.is_set)),
            clear_locations(elements_chain_match('(href="[^"]+")')),
        )
        self.assertEqual(
            clear_locations(element_chain_key_filter("href", "boo..", PropertyOperator.is_not_set)),
            clear_locations(not_call(elements_chain_match('(href="[^"]+")'))),
        )
        self.assertEqual(
            clear_locations(element_chain_key_filter("href", "boo..", PropertyOperator.icontains)),
            clear_locations(elements_chain_imatch('(href="[^"]*boo\\.\\.[^"]*")')),
        )
        self.assertEqual(
            clear_locations(element_chain_key_filter("href", "boo..", PropertyOperator.not_icontains)),
            clear_locations(not_call(elements_chain_imatch('(href="[^"]*boo\\.\\.[^"]*")'))),
        )
        self.assertEqual(
            clear_locations(element_chain_key_filter("href", "boo..", PropertyOperator.regex)),
            clear_locations(elements_chain_match('(href="boo..")')),
        )
        self.assertEqual(
            clear_locations(element_chain_key_filter("href", "boo..", PropertyOperator.not_regex)),
            clear_locations(not_call(elements_chain_match('(href="boo..")'))),
        )
        self.assertEqual(
            clear_locations(element_chain_key_filter("href", "boo..", PropertyOperator.exact)),
            clear_locations(elements_chain_match('(href="boo\\.\\.")')),
        )
        self.assertEqual(
            clear_locations(element_chain_key_filter("href", "boo..", PropertyOperator.is_not)),
            clear_locations(not_call(elements_chain_match('(href="boo\\.\\.")'))),
        )

    def test_action_to_expr(self):
        action1 = Action.objects.create(team=self.team)
        ActionStep.objects.create(
            event="$autocapture",
            action=action1,
            selector="a.nav-link.active",
            tag_name="a",
        )
        self.assertEqual(
            clear_locations(action_to_expr(action1)),
            self._parse_expr(
                "event = '$autocapture' and elements_chain =~ {regex1} and elements_chain =~ {regex2}",
                {
                    "regex1": ast.Constant(
                        value='a.*?\\.active\\..*?nav\\-link([-_a-zA-Z0-9\\.:"= ]*?)?($|;|:([^;^\\s]*(;|$|\\s)))'
                    ),
                    "regex2": ast.Constant(value="(^|;)a(\\.|$|;|:)"),
                },
            ),
        )

        action2 = Action.objects.create(team=self.team)
        ActionStep.objects.create(
            event="$pageview",
            action=action2,
            url="https://example.com",
            url_matching="contains",
        )
        self.assertEqual(
            clear_locations(action_to_expr(action2)),
            self._parse_expr("event = '$pageview' and properties.$current_url like '%https://example.com%'"),
        )

        action3 = Action.objects.create(team=self.team)
        ActionStep.objects.create(
            event="$pageview",
            action=action3,
            url="https://example2.com",
            url_matching="regex",
        )
        ActionStep.objects.create(
            event="custom",
            action=action3,
            url="https://example3.com",
            url_matching="exact",
        )
        self.assertEqual(
            clear_locations(action_to_expr(action3)),
            self._parse_expr(
                "{s1} or {s2}",
                {
                    "s1": self._parse_expr("event = '$pageview' and properties.$current_url =~ 'https://example2.com'"),
                    "s2": self._parse_expr("event = 'custom' and properties.$current_url = 'https://example3.com'"),
                },
            ),
        )

        action4 = Action.objects.create(team=self.team)
        ActionStep.objects.create(event="$pageview", action=action4)
        ActionStep.objects.create(event=None, action=action4)
        self.assertEqual(
            clear_locations(action_to_expr(action4)),
            self._parse_expr("event = '$pageview' OR true"),  # All events just resolve to "true"
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
            "The 'event' property filter only works in 'event' scope, not in 'person' scope",
        )

    def test_entity_to_expr_actions_type_with_id(self):
        action_mock = MagicMock()
        with patch("posthog.models.Action.objects.get", return_value=action_mock):
            entity = RetentionEntity(**{"type": TREND_FILTER_TYPE_ACTIONS, "id": 123})
            result = entity_to_expr(entity)
            self.assertIsInstance(result, ast.Expr)

    def test_entity_to_expr_events_type_with_id(self):
        entity = RetentionEntity(**{"type": TREND_FILTER_TYPE_EVENTS, "id": "event_id"})
        result = entity_to_expr(entity)
        expected = ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["events", "event"]),
            right=ast.Constant(value="event_id"),
        )
        self.assertEqual(result, expected)

    def test_entity_to_expr_events_type_without_id(self):
        entity = RetentionEntity(**{"type": TREND_FILTER_TYPE_EVENTS, "id": None})
        result = entity_to_expr(entity)
        self.assertEqual(result, ast.Constant(value=True))

    def test_entity_to_expr_default_case(self):
        entity = RetentionEntity()
        result = entity_to_expr(entity, default_event="default_event")
        expected = ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["events", "event"]),
            right=ast.Constant(value="default_event"),
        )
        self.assertEqual(result, expected)
