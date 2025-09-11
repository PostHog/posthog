import pytest

from posthog.schema import (
    ActionsNode,
    EmptyPropertyFilter,
    EventPropertyFilter,
    EventsNode,
    PersonPropertyFilter,
    PropertyOperator,
)

from posthog.hogql_queries.insights.utils.entities import is_equal, is_superset

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
