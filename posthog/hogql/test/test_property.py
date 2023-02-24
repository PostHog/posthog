from typing import List, Union, cast

from posthog.constants import PropertyOperatorType
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import (
    action_to_expr,
    element_chain_key_filter,
    has_aggregation,
    property_to_expr,
    selector_to_expr,
    tag_name_to_expr,
)
from posthog.models import Action, ActionStep, Property
from posthog.models.property import PropertyGroup
from posthog.schema import HogQLPropertyFilter, PropertyOperator
from posthog.test.base import BaseTest

elements_chain_match = lambda x: parse_expr("match(elements_chain, {regex})", {"regex": ast.Constant(value=str(x))})
not_call = lambda x: ast.Call(name="not", args=[x])


class TestProperty(BaseTest):
    def test_has_aggregation(self):
        self.assertEqual(has_aggregation(parse_expr("properties.a = 'b'")), False)
        self.assertEqual(has_aggregation(parse_expr("if(1,2,3)")), False)
        self.assertEqual(has_aggregation(parse_expr("if(1,2,avg(3))")), True)
        self.assertEqual(has_aggregation(parse_expr("count()")), True)
        self.assertEqual(has_aggregation(parse_expr("sum(properties.bla)")), True)

    def test_property_to_expr_hogql(self):
        self.assertEqual(property_to_expr({"type": "hogql", "key": "1"}), ast.Constant(value=1))
        self.assertEqual(property_to_expr(Property(type="hogql", key="1")), ast.Constant(value=1))
        self.assertEqual(property_to_expr(HogQLPropertyFilter(type="hogql", key="1")), ast.Constant(value=1))

    def test_property_to_expr_event(self):
        self.assertEqual(
            property_to_expr({"key": "a", "value": "b"}),
            parse_expr("properties.a = 'b'"),
        )
        self.assertEqual(
            property_to_expr({"type": "event", "key": "a", "value": "b"}),
            parse_expr("properties.a = 'b'"),
        )
        self.assertEqual(
            property_to_expr({"type": "event", "key": "a", "value": "b", "operator": "is_set"}),
            parse_expr("properties.a is not null"),
        )
        self.assertEqual(
            property_to_expr({"type": "event", "key": "a", "value": "b", "operator": "is_not_set"}),
            parse_expr("properties.a is null"),
        )
        self.assertEqual(
            property_to_expr({"type": "event", "key": "a", "value": "b", "operator": "exact"}),
            parse_expr("properties.a = 'b'"),
        )
        self.assertEqual(
            property_to_expr({"type": "event", "key": "a", "value": "b", "operator": "is_not"}),
            parse_expr("properties.a != 'b'"),
        )
        self.assertEqual(
            property_to_expr({"type": "event", "key": "a", "value": "3", "operator": "gt"}),
            parse_expr("properties.a > '3'"),
        )
        self.assertEqual(
            property_to_expr({"type": "event", "key": "a", "value": "3", "operator": "lt"}),
            parse_expr("properties.a < '3'"),
        )
        self.assertEqual(
            property_to_expr({"type": "event", "key": "a", "value": "3", "operator": "gte"}),
            parse_expr("properties.a >= '3'"),
        )
        self.assertEqual(
            property_to_expr({"type": "event", "key": "a", "value": "3", "operator": "lte"}),
            parse_expr("properties.a <= '3'"),
        )
        self.assertEqual(
            property_to_expr({"type": "event", "key": "a", "value": "3", "operator": "icontains"}),
            parse_expr("properties.a ilike '%3%'"),
        )
        self.assertEqual(
            property_to_expr({"type": "event", "key": "a", "value": "3", "operator": "not_icontains"}),
            parse_expr("properties.a not ilike '%3%'"),
        )
        self.assertEqual(
            property_to_expr({"type": "event", "key": "a", "value": ".*", "operator": "regex"}),
            parse_expr("match(properties.a, '.*')"),
        )
        self.assertEqual(
            property_to_expr({"type": "event", "key": "a", "value": ".*", "operator": "not_regex"}),
            parse_expr("not(match(properties.a, '.*'))"),
        )

    def test_property_to_expr_event_list(self):
        # positive
        self.assertEqual(
            property_to_expr({"type": "event", "key": "a", "value": ["b", "c"], "operator": "exact"}),
            parse_expr("properties.a = 'b' or properties.a = 'c'"),
        )
        self.assertEqual(
            property_to_expr({"type": "event", "key": "a", "value": ["b", "c"], "operator": "icontains"}),
            parse_expr("properties.a ilike '%b%' or properties.a ilike '%c%'"),
        )
        self.assertEqual(
            property_to_expr({"type": "event", "key": "a", "value": ["b", "c"], "operator": "regex"}),
            parse_expr("match(properties.a, 'b') or match(properties.a, 'c')"),
        )
        # negative
        self.assertEqual(
            property_to_expr({"type": "event", "key": "a", "value": ["b", "c"], "operator": "is_not"}),
            parse_expr("properties.a != 'b' and properties.a != 'c'"),
        )
        self.assertEqual(
            property_to_expr({"type": "event", "key": "a", "value": ["b", "c"], "operator": "not_icontains"}),
            parse_expr("properties.a not ilike '%b%' and properties.a not ilike '%c%'"),
        )
        self.assertEqual(
            property_to_expr({"type": "event", "key": "a", "value": ["b", "c"], "operator": "not_regex"}),
            parse_expr("not(match(properties.a, 'b')) and not(match(properties.a, 'c'))"),
        )

    def test_property_to_expr_feature(self):
        self.assertEqual(
            property_to_expr({"type": "event", "key": "a", "value": "b", "operator": "exact"}),
            parse_expr("properties.a = 'b'"),
        )

    def test_property_to_expr_person(self):
        self.assertEqual(
            property_to_expr({"type": "person", "key": "a", "value": "b", "operator": "exact"}),
            parse_expr("person.properties.a = 'b'"),
        )

    def test_property_to_expr_element(self):
        self.assertEqual(
            property_to_expr({"type": "element", "key": "selector", "value": "div", "operator": "exact"}),
            selector_to_expr("div"),
        )
        self.assertEqual(
            property_to_expr({"type": "element", "key": "selector", "value": "div", "operator": "is_not"}),
            not_call(selector_to_expr("div")),
        )
        self.assertEqual(
            property_to_expr({"type": "element", "key": "tag_name", "value": "div", "operator": "exact"}),
            tag_name_to_expr("div"),
        )
        self.assertEqual(
            property_to_expr({"type": "element", "key": "tag_name", "value": "div", "operator": "is_not"}),
            not_call(tag_name_to_expr("div")),
        )
        self.assertEqual(
            property_to_expr({"type": "element", "key": "href", "value": "href-text.", "operator": "exact"}),
            element_chain_key_filter("href", "href-text.", PropertyOperator.exact),
        )
        self.assertEqual(
            property_to_expr({"type": "element", "key": "text", "value": "text-text.", "operator": "regex"}),
            element_chain_key_filter("text", "text-text.", PropertyOperator.regex),
        )

    def test_property_groups(self):
        self.assertEqual(
            property_to_expr(
                PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(type="person", key="a", value="b", operator="exact"),
                        Property(type="event", key="e", value="b", operator="exact"),
                    ],
                )
            ),
            parse_expr("person.properties.a = 'b' and properties.e = 'b'"),
        )

        self.assertEqual(
            property_to_expr(
                PropertyGroup(
                    type=PropertyOperatorType.OR,
                    values=[
                        Property(type="person", key="a", value="b", operator="exact"),
                        Property(type="event", key="e", value="b", operator="exact"),
                    ],
                )
            ),
            parse_expr("person.properties.a = 'b' or properties.e = 'b'"),
        )

    def test_property_groups_single(self):
        self.assertEqual(
            property_to_expr(
                PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(type="person", key="a", value="b", operator="exact"),
                    ],
                )
            ),
            parse_expr("person.properties.a = 'b'"),
        )

        self.assertEqual(
            property_to_expr(
                PropertyGroup(
                    type=PropertyOperatorType.OR, values=[Property(type="event", key="e", value="b", operator="exact")]
                )
            ),
            parse_expr("properties.e = 'b'"),
        )

    def test_property_groups_combined(self):
        self.assertEqual(
            property_to_expr(
                PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=cast(
                        Union[List[Property], List[PropertyGroup]],
                        [
                            Property(type="person", key="a", value="b", operator="exact"),
                            PropertyGroup(
                                type=PropertyOperatorType.OR,
                                values=[
                                    Property(type="person", key="a", value="b", operator="exact"),
                                    Property(type="event", key="e", value="b", operator="exact"),
                                ],
                            ),
                        ],
                    ),
                )
            ),
            parse_expr("person.properties.a = 'b' and (person.properties.a = 'b' or properties.e = 'b')"),
        )

    def test_tag_name_to_expr(self):
        self.assertEqual(tag_name_to_expr("a"), elements_chain_match("(^|;)a(\\.|$|;|:)"))

    def test_selector_to_expr(self):
        self.assertEqual(
            selector_to_expr("div"), elements_chain_match('div([-_a-zA-Z0-9\\.:"= ]*?)?($|;|:([^;^\\s]*(;|$|\\s)))')
        )
        self.assertEqual(
            selector_to_expr("div > div"),
            elements_chain_match(
                'div([-_a-zA-Z0-9\\.:"= ]*?)?($|;|:([^;^\\s]*(;|$|\\s)))div([-_a-zA-Z0-9\\.:"= ]*?)?($|;|:([^;^\\s]*(;|$|\\s))).*'
            ),
        )
        self.assertEqual(
            selector_to_expr("a[href='boo']"),
            elements_chain_match('a.*?href="boo".*?([-_a-zA-Z0-9\\.:"= ]*?)?($|;|:([^;^\\s]*(;|$|\\s)))'),
        )
        self.assertEqual(
            selector_to_expr(".class"),
            elements_chain_match('.*?\\.class([-_a-zA-Z0-9\\.:"= ]*?)?($|;|:([^;^\\s]*(;|$|\\s)))'),
        )
        self.assertEqual(
            selector_to_expr("#withid"),
            elements_chain_match('#withid([-_a-zA-Z0-9\\.:"= ]*?)?($|;|:([^;^\\s]*(;|$|\\s)))'),
        )

    def test_elements_chain_key_filter(self):
        self.assertEqual(
            element_chain_key_filter("href", "boo..", PropertyOperator.is_set), elements_chain_match('(href="[^"]+")')
        )
        self.assertEqual(
            element_chain_key_filter("href", "boo..", PropertyOperator.is_not_set),
            not_call(elements_chain_match('(href="[^"]+")')),
        )
        self.assertEqual(
            element_chain_key_filter("href", "boo..", PropertyOperator.icontains),
            elements_chain_match('(?i)(href="[^"]*boo\\.\\.[^"]*")'),
        )
        self.assertEqual(
            element_chain_key_filter("href", "boo..", PropertyOperator.not_icontains),
            not_call(elements_chain_match('(?i)(href="[^"]*boo\\.\\.[^"]*")')),
        )
        self.assertEqual(
            element_chain_key_filter("href", "boo..", PropertyOperator.regex), elements_chain_match('(href="boo..")')
        )
        self.assertEqual(
            element_chain_key_filter("href", "boo..", PropertyOperator.not_regex),
            not_call(elements_chain_match('(href="boo..")')),
        )
        self.assertEqual(
            element_chain_key_filter("href", "boo..", PropertyOperator.exact),
            elements_chain_match('(href="boo\\.\\.")'),
        )
        self.assertEqual(
            element_chain_key_filter("href", "boo..", PropertyOperator.is_not),
            not_call(elements_chain_match('(href="boo\\.\\.")')),
        )

    def test_action_to_expr(self):
        action1 = Action.objects.create(team=self.team)
        ActionStep.objects.create(event="$autocapture", action=action1, selector="a.nav-link.active", tag_name="a")
        self.assertEqual(
            action_to_expr(action1),
            parse_expr(
                "event = '$autocapture' and match(elements_chain, {regex1}) and match(elements_chain, {regex2})",
                {
                    "regex1": ast.Constant(
                        value='a.*?\\.active\\..*?nav-link([-_a-zA-Z0-9\\.:"= ]*?)?($|;|:([^;^\\s]*(;|$|\\s)))'
                    ),
                    "regex2": ast.Constant(value="(^|;)a(\\.|$|;|:)"),
                },
            ),
        )

        action2 = Action.objects.create(team=self.team)
        ActionStep.objects.create(event="$pageview", action=action2, url="https://example.com", url_matching="contains")
        self.assertEqual(
            action_to_expr(action2),
            parse_expr("event = '$pageview' and properties.$current_url like '%https://example.com%'"),
        )

        action3 = Action.objects.create(team=self.team)
        ActionStep.objects.create(event="$pageview", action=action3, url="https://example2.com", url_matching="regex")
        ActionStep.objects.create(event="custom", action=action3, url="https://example3.com", url_matching="exact")
        self.assertEqual(
            action_to_expr(action3),
            parse_expr(
                "{s1} or {s2}",
                {
                    "s1": parse_expr("event = '$pageview' and match(properties.$current_url, 'https://example2.com')"),
                    "s2": parse_expr("event = 'custom' and properties.$current_url = 'https://example3.com'"),
                },
            ),
        )
