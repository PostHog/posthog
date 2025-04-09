from typing import Any, Optional
import pytest
from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import print_ast
from posthog.hogql.visitor import clear_locations
from posthog.hogql_queries.insights.utils.entities import entity_to_expr, is_equal, is_superset
from posthog.models.action.action import Action
from posthog.models.team.team import Team
from posthog.schema import (
    ActionsNode,
    EmptyPropertyFilter,
    EventPropertyFilter,
    EventsNode,
    PersonPropertyFilter,
    PropertyOperator,
)
from posthog.test.base import BaseTest
from posthog.types import EntityNode


testdata_equals = [
    (EventsNode(), EventsNode(), True),
    (EventsNode(event="$pageview"), EventsNode(event="$pageview"), True),
    (ActionsNode(id=1), ActionsNode(id=1), True),
    # different type
    (EventsNode(), ActionsNode(id=1), False),
    # different event
    (EventsNode(event="$pageview"), EventsNode(event="$pageleave"), False),
    # different action
    (ActionsNode(id=1), ActionsNode(id=2), False),
    (
        EventsNode(
            properties=[EventPropertyFilter(key="some_key", value="some_value", operator=PropertyOperator.EXACT)]
        ),
        EventsNode(
            properties=[EventPropertyFilter(key="some_key", value="some_value", operator=PropertyOperator.EXACT)]
        ),
        True,
    ),
    # none vs empty properties
    (
        EventsNode(properties=None),
        EventsNode(properties=[]),
        True,
    ),
    # empty property filter vs empty properties
    (
        EventsNode(properties=[EmptyPropertyFilter()]),
        EventsNode(properties=[]),
        True,
    ),
    # different type
    (
        EventsNode(
            properties=[PersonPropertyFilter(key="some_key", value="some_value", operator=PropertyOperator.EXACT)]
        ),
        EventsNode(
            properties=[EventPropertyFilter(key="some_key", value="some_value", operator=PropertyOperator.EXACT)]
        ),
        False,
    ),
    # different key
    (
        EventsNode(
            properties=[EventPropertyFilter(key="some_key", value="some_value", operator=PropertyOperator.EXACT)]
        ),
        EventsNode(
            properties=[EventPropertyFilter(key="other_key", value="some_value", operator=PropertyOperator.EXACT)]
        ),
        False,
    ),
    # different value
    (
        EventsNode(
            properties=[EventPropertyFilter(key="some_key", value="some_value", operator=PropertyOperator.EXACT)]
        ),
        EventsNode(
            properties=[EventPropertyFilter(key="some_key", value="other_value", operator=PropertyOperator.EXACT)]
        ),
        False,
    ),
    # different operator
    (
        EventsNode(
            properties=[EventPropertyFilter(key="some_key", value="some_value", operator=PropertyOperator.EXACT)]
        ),
        EventsNode(
            properties=[EventPropertyFilter(key="some_key", value="some_value", operator=PropertyOperator.IS_NOT)]
        ),
        False,
    ),
    # different fixed properties
    (
        EventsNode(
            fixedProperties=[EventPropertyFilter(key="some_key", value="some_value", operator=PropertyOperator.EXACT)]
        ),
        EventsNode(
            fixedProperties=[EventPropertyFilter(key="other_key", value="some_value", operator=PropertyOperator.EXACT)]
        ),
        False,
    ),
]


@pytest.mark.parametrize("a,b,expected", testdata_equals)
def test_is_equal(a, b, expected):
    assert is_equal(a, b) == expected


testdata_superset = [
    # everything equal
    (
        EventsNode(
            properties=[EventPropertyFilter(key="some_key", value="some_value", operator=PropertyOperator.EXACT)]
        ),
        EventsNode(
            properties=[EventPropertyFilter(key="some_key", value="some_value", operator=PropertyOperator.EXACT)]
        ),
        True,
    ),
    # additional node
    (
        EventsNode(
            properties=[
                EventPropertyFilter(key="some_key", value="some_value", operator=PropertyOperator.EXACT),
                PersonPropertyFilter(key="some_key", value="some_value", operator=PropertyOperator.EXACT),
            ]
        ),
        EventsNode(
            properties=[EventPropertyFilter(key="some_key", value="some_value", operator=PropertyOperator.EXACT)]
        ),
        True,
    ),
    # subset
    (
        EventsNode(
            properties=[EventPropertyFilter(key="some_key", value="some_value", operator=PropertyOperator.EXACT)]
        ),
        EventsNode(
            properties=[
                EventPropertyFilter(key="some_key", value="some_value", operator=PropertyOperator.EXACT),
                PersonPropertyFilter(key="some_key", value="some_value", operator=PropertyOperator.EXACT),
            ]
        ),
        False,
    ),
    (EventsNode(), EventsNode(), True),
    # different node type
    (EventsNode(), ActionsNode(id=1), False),
    # none vs empty properties
    (
        EventsNode(properties=None),
        EventsNode(properties=[]),
        True,
    ),
    # empty property filter vs empty properties
    (
        EventsNode(properties=[EmptyPropertyFilter()]),
        EventsNode(properties=[]),
        True,
    ),
    # different type
    (
        EventsNode(
            properties=[PersonPropertyFilter(key="some_key", value="some_value", operator=PropertyOperator.EXACT)]
        ),
        EventsNode(
            properties=[EventPropertyFilter(key="some_key", value="some_value", operator=PropertyOperator.EXACT)]
        ),
        False,
    ),
]


@pytest.mark.parametrize("a,b,expected", testdata_equals)
def test_is_superset(a, b, expected):
    assert is_superset(a, b) == expected


class TestEntityToExpr(BaseTest):
    maxDiff = None

    def _parse_expr(self, expr: str, placeholders: Optional[dict[str, Any]] = None):
        return clear_locations(parse_expr(expr, placeholders=placeholders))

    def _entity_to_expr(self, entity: EntityNode, team: Team):
        return clear_locations(entity_to_expr(entity, team))

    def _parse_select(self, select: str, placeholders: Optional[dict[str, Any]] = None):
        return clear_locations(parse_select(select, placeholders=placeholders))

    def _print_ast(self, node: ast.Expr):
        return print_ast(
            node,
            dialect="hogql",
            context=HogQLContext(team_id=self.team.pk, enable_select_queries=True),
        )

    def test_event_node(self):
        self.assertEqual(
            self._entity_to_expr(EventsNode(event="$pageview"), self.team),
            self._parse_expr("event = '$pageview'"),
        )

    def test_event_node_all_events(self):
        self.assertEqual(
            self._entity_to_expr(EventsNode(), self.team),
            self._parse_expr("true"),
        )

    def test_action_node(self):
        action = Action.objects.create(
            team=self.team,
            steps_json=[
                {"event": "$autocapture", "href": "https://example4.com", "href_matching": "regex"},
                {"event": "$pageview"},
                {"event": None},
            ],
        )
        self.assertEqual(
            self._entity_to_expr(ActionsNode(id=action.pk), self.team),
            self._parse_expr(
                "(event = '$autocapture' and elements_chain_href =~ 'https://example4.com') OR event = '$pageview' OR true"
            ),
        )

    def test_event_node_with_properties(self):
        self.assertEqual(
            self._entity_to_expr(
                EventsNode(
                    event="$pageview",
                    properties=[
                        EventPropertyFilter(key="some_key", value="some_value", operator=PropertyOperator.EXACT)
                    ],
                ),
                self.team,
            ),
            self._parse_expr("event = '$pageview' and properties.some_key = 'some_value'"),
        )

    def test_event_node_with_fixed_properties(self):
        self.assertEqual(
            self._entity_to_expr(
                EventsNode(
                    event="$pageview",
                    fixedProperties=[
                        EventPropertyFilter(key="some_key", value="some_value", operator=PropertyOperator.EXACT)
                    ],
                ),
                self.team,
            ),
            self._parse_expr("event = '$pageview' and properties.some_key = 'some_value'"),
        )

    def test_action_node_with_properties(self):
        action = Action.objects.create(
            team=self.team,
            steps_json=[
                {"event": "$autocapture", "href": "https://example4.com", "href_matching": "regex"},
            ],
        )
        self.assertEqual(
            self._entity_to_expr(
                ActionsNode(
                    id=action.pk,
                    properties=[
                        EventPropertyFilter(key="some_key", value="some_value", operator=PropertyOperator.EXACT)
                    ],
                ),
                self.team,
            ),
            self._parse_expr(
                "event = '$autocapture' and elements_chain_href =~ 'https://example4.com' and properties.some_key = 'some_value'"
            ),
        )
