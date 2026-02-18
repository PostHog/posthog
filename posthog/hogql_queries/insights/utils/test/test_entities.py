import pytest

from posthog.schema import (
    ActionsNode,
    DataWarehouseNode,
    EmptyPropertyFilter,
    EventPropertyFilter,
    EventsNode,
    FilterLogicalOperator,
    GroupNode,
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
    # group node vs non-group node
    (
        GroupNode(operator=FilterLogicalOperator.OR_, nodes=[EventsNode(event="$pageview")]),
        EventsNode(event="$pageview"),
        False,
    ),
]

testdata_group_equals = [
    # identical single-node groups
    (
        GroupNode(operator=FilterLogicalOperator.OR_, nodes=[EventsNode(event="$pageview")]),
        GroupNode(operator=FilterLogicalOperator.OR_, nodes=[EventsNode(event="$pageview")]),
        True,
    ),
    # different operator
    (
        GroupNode(operator=FilterLogicalOperator.OR_, nodes=[EventsNode(event="$pageview")]),
        GroupNode(operator=FilterLogicalOperator.AND_, nodes=[EventsNode(event="$pageview")]),
        False,
    ),
    # different child event
    (
        GroupNode(operator=FilterLogicalOperator.OR_, nodes=[EventsNode(event="$pageview")]),
        GroupNode(operator=FilterLogicalOperator.OR_, nodes=[EventsNode(event="$pageleave")]),
        False,
    ),
    # different number of children
    (
        GroupNode(operator=FilterLogicalOperator.OR_, nodes=[EventsNode(event="$pageview")]),
        GroupNode(
            operator=FilterLogicalOperator.OR_,
            nodes=[EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
        ),
        False,
    ),
    # same children in different order
    (
        GroupNode(
            operator=FilterLogicalOperator.OR_,
            nodes=[EventsNode(event="$pageview"), ActionsNode(id=1)],
        ),
        GroupNode(
            operator=FilterLogicalOperator.OR_,
            nodes=[ActionsNode(id=1), EventsNode(event="$pageview")],
        ),
        True,
    ),
    # mixed node types reordered
    (
        GroupNode(
            operator=FilterLogicalOperator.AND_,
            nodes=[
                EventsNode(event="$pageview"),
                ActionsNode(id=1),
                DataWarehouseNode(
                    id="dw1", id_field="id", table_name="t", distinct_id_field="did", timestamp_field="ts"
                ),
            ],
        ),
        GroupNode(
            operator=FilterLogicalOperator.AND_,
            nodes=[
                DataWarehouseNode(
                    id="dw1", id_field="id", table_name="t", distinct_id_field="did", timestamp_field="ts"
                ),
                EventsNode(event="$pageview"),
                ActionsNode(id=1),
            ],
        ),
        True,
    ),
    # duplicate children must match (multiset comparison)
    (
        GroupNode(
            operator=FilterLogicalOperator.OR_,
            nodes=[EventsNode(event="$pageview"), EventsNode(event="$pageview")],
        ),
        GroupNode(
            operator=FilterLogicalOperator.OR_,
            nodes=[EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
        ),
        False,
    ),
    # same group-level properties
    (
        GroupNode(
            operator=FilterLogicalOperator.OR_,
            nodes=[EventsNode(event="$pageview")],
            properties=[EventPropertyFilter(key="k", value="v", operator=PropertyOperator.EXACT)],
        ),
        GroupNode(
            operator=FilterLogicalOperator.OR_,
            nodes=[EventsNode(event="$pageview")],
            properties=[EventPropertyFilter(key="k", value="v", operator=PropertyOperator.EXACT)],
        ),
        True,
    ),
    # different group-level properties
    (
        GroupNode(
            operator=FilterLogicalOperator.OR_,
            nodes=[EventsNode(event="$pageview")],
            properties=[EventPropertyFilter(key="k", value="v1", operator=PropertyOperator.EXACT)],
        ),
        GroupNode(
            operator=FilterLogicalOperator.OR_,
            nodes=[EventsNode(event="$pageview")],
            properties=[EventPropertyFilter(key="k", value="v2", operator=PropertyOperator.EXACT)],
        ),
        False,
    ),
    # child node properties differ
    (
        GroupNode(
            operator=FilterLogicalOperator.OR_,
            nodes=[
                EventsNode(
                    event="$pageview",
                    properties=[EventPropertyFilter(key="k", value="v1", operator=PropertyOperator.EXACT)],
                ),
            ],
        ),
        GroupNode(
            operator=FilterLogicalOperator.OR_,
            nodes=[
                EventsNode(
                    event="$pageview",
                    properties=[EventPropertyFilter(key="k", value="v2", operator=PropertyOperator.EXACT)],
                ),
            ],
        ),
        False,
    ),
]


@pytest.mark.parametrize("a,b,expected", testdata_equals + testdata_group_equals)
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
    # a has more properties (more filtered), not a superset
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
        False,
    ),
    # a has fewer properties (less filtered), a is superset of b
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
        True,
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

testdata_group_superset = [
    # a has fewer properties (less filtered) so a is superset of b
    (
        GroupNode(
            operator=FilterLogicalOperator.OR_,
            nodes=[EventsNode(event="$pageview")],
            properties=[EventPropertyFilter(key="k1", value="v1", operator=PropertyOperator.EXACT)],
        ),
        GroupNode(
            operator=FilterLogicalOperator.OR_,
            nodes=[EventsNode(event="$pageview")],
            properties=[
                EventPropertyFilter(key="k1", value="v1", operator=PropertyOperator.EXACT),
                EventPropertyFilter(key="k2", value="v2", operator=PropertyOperator.EXACT),
            ],
        ),
        True,
    ),
    # a has more properties (more filtered) so a is NOT superset of b
    (
        GroupNode(
            operator=FilterLogicalOperator.OR_,
            nodes=[EventsNode(event="$pageview")],
            properties=[
                EventPropertyFilter(key="k1", value="v1", operator=PropertyOperator.EXACT),
                EventPropertyFilter(key="k2", value="v2", operator=PropertyOperator.EXACT),
            ],
        ),
        GroupNode(
            operator=FilterLogicalOperator.OR_,
            nodes=[EventsNode(event="$pageview")],
            properties=[EventPropertyFilter(key="k1", value="v1", operator=PropertyOperator.EXACT)],
        ),
        False,
    ),
    # different operator means not superset
    (
        GroupNode(operator=FilterLogicalOperator.OR_, nodes=[EventsNode(event="$pageview")]),
        GroupNode(operator=FilterLogicalOperator.AND_, nodes=[EventsNode(event="$pageview")]),
        False,
    ),
]


@pytest.mark.parametrize("a,b,expected", testdata_superset + testdata_group_superset)
def test_is_superset(a, b, expected):
    assert is_superset(a, b) == expected
