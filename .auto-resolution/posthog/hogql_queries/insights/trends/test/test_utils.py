import pytest

from posthog.schema import (
    BaseMathType,
    BreakdownType,
    CountPerActorMathType,
    EventsNode,
    MathGroupTypeIndex,
    PropertyMathType,
)

from posthog.hogql_queries.insights.trends.utils import get_properties_chain, is_groups_math


def test_properties_chain_person():
    p1 = get_properties_chain(breakdown_type=BreakdownType.PERSON, breakdown_field="field", group_type_index=None)
    assert p1 == ["person", "properties", "field"]

    p2 = get_properties_chain(breakdown_type=BreakdownType.PERSON, breakdown_field="field", group_type_index=1)
    assert p2 == ["person", "properties", "field"]


def test_properties_chain_session():
    p1 = get_properties_chain(breakdown_type=BreakdownType.SESSION, breakdown_field="anything", group_type_index=None)
    assert p1 == ["session", "anything"]

    p2 = get_properties_chain(breakdown_type=BreakdownType.SESSION, breakdown_field="anything", group_type_index=1)
    assert p2 == ["session", "anything"]

    p3 = get_properties_chain(
        breakdown_type=BreakdownType.SESSION, breakdown_field="$session_duration", group_type_index=None
    )
    assert p3 == ["session", "$session_duration"]


def test_properties_chain_groups():
    p1 = get_properties_chain(breakdown_type=BreakdownType.GROUP, breakdown_field="anything", group_type_index=1)
    assert p1 == ["group_1", "properties", "anything"]

    with pytest.raises(Exception) as e:
        get_properties_chain(breakdown_type=BreakdownType.GROUP, breakdown_field="anything", group_type_index=None)
        assert "group_type_index missing from params" in str(e.value)


def test_properties_chain_events():
    p1 = get_properties_chain(breakdown_type=BreakdownType.EVENT, breakdown_field="anything", group_type_index=None)
    assert p1 == ["properties", "anything"]

    p2 = get_properties_chain(breakdown_type=BreakdownType.EVENT, breakdown_field="anything_else", group_type_index=1)
    assert p2 == ["properties", "anything_else"]


def test_properties_chain_warehouse_props():
    p1 = get_properties_chain(
        breakdown_type=BreakdownType.DATA_WAREHOUSE_PERSON_PROPERTY,
        breakdown_field="some_table.field",
        group_type_index=None,
    )
    assert p1 == ["person", "some_table", "field"]

    p2 = get_properties_chain(
        breakdown_type=BreakdownType.DATA_WAREHOUSE_PERSON_PROPERTY,
        breakdown_field="some_table",
        group_type_index=None,
    )
    assert p2 == ["person", "some_table"]

    p3 = get_properties_chain(
        breakdown_type=BreakdownType.DATA_WAREHOUSE_PERSON_PROPERTY,
        breakdown_field="some_table.props.obj.blah",
        group_type_index=None,
    )
    assert p3 == ["person", "some_table", "props", "obj", "blah"]


@pytest.mark.parametrize(
    "math,math_group_type_index,expected",
    [
        # Cases that should return True
        ("unique_group", MathGroupTypeIndex.NUMBER_0, True),
        ("unique_group", MathGroupTypeIndex.NUMBER_1, True),
        ("unique_group", MathGroupTypeIndex.NUMBER_2, True),
        (BaseMathType.WEEKLY_ACTIVE, MathGroupTypeIndex.NUMBER_0, True),
        (BaseMathType.WEEKLY_ACTIVE, MathGroupTypeIndex.NUMBER_1, True),
        (BaseMathType.WEEKLY_ACTIVE, MathGroupTypeIndex.NUMBER_2, True),
        (BaseMathType.MONTHLY_ACTIVE, MathGroupTypeIndex.NUMBER_0, True),
        (BaseMathType.MONTHLY_ACTIVE, MathGroupTypeIndex.NUMBER_1, True),
        (BaseMathType.MONTHLY_ACTIVE, MathGroupTypeIndex.NUMBER_2, True),
        (BaseMathType.DAU, MathGroupTypeIndex.NUMBER_0, True),
        (BaseMathType.DAU, MathGroupTypeIndex.NUMBER_1, True),
        (BaseMathType.DAU, MathGroupTypeIndex.NUMBER_2, True),
        # Cases that should return False - missing group index
        ("unique_group", None, False),
        (BaseMathType.WEEKLY_ACTIVE, None, False),
        (BaseMathType.MONTHLY_ACTIVE, None, False),
        (BaseMathType.DAU, None, False),
        # Cases that should return False - unsupported math types
        (BaseMathType.TOTAL, MathGroupTypeIndex.NUMBER_0, False),
        (BaseMathType.TOTAL, None, False),
        (BaseMathType.UNIQUE_SESSION, MathGroupTypeIndex.NUMBER_0, False),
        (BaseMathType.UNIQUE_SESSION, None, False),
        (BaseMathType.FIRST_TIME_FOR_USER, MathGroupTypeIndex.NUMBER_0, False),
        (BaseMathType.FIRST_TIME_FOR_USER, None, False),
    ],
)
def test_is_groups_math_events_node(math, math_group_type_index, expected):
    """Test is_groups_math with EventsNode for various math types and group indices."""
    series = EventsNode(event="$pageview", math=math, math_group_type_index=math_group_type_index)
    assert is_groups_math(series) == expected


@pytest.mark.parametrize(
    "math,math_property,math_group_type_index,expected",
    [
        # Property math types should always return False, even with group index
        (PropertyMathType.AVG, "$browser", MathGroupTypeIndex.NUMBER_0, False),
        (PropertyMathType.SUM, "$revenue", MathGroupTypeIndex.NUMBER_1, False),
        (PropertyMathType.MIN, "$price", MathGroupTypeIndex.NUMBER_2, False),
        (PropertyMathType.MAX, "$price", MathGroupTypeIndex.NUMBER_0, False),
        (PropertyMathType.MEDIAN, "$duration", MathGroupTypeIndex.NUMBER_1, False),
        (PropertyMathType.P90, "$duration", MathGroupTypeIndex.NUMBER_2, False),
        (PropertyMathType.P95, "$duration", MathGroupTypeIndex.NUMBER_0, False),
        (PropertyMathType.P99, "$duration", MathGroupTypeIndex.NUMBER_1, False),
        # Property math without group index should also return False
        (PropertyMathType.AVG, "$browser", None, False),
        (PropertyMathType.SUM, "$revenue", None, False),
    ],
)
def test_is_groups_math_property_math(math, math_property, math_group_type_index, expected):
    """Test is_groups_math with property math types (should always be False)."""
    series = EventsNode(
        event="$pageview", math=math, math_property=math_property, math_group_type_index=math_group_type_index
    )
    assert is_groups_math(series) == expected


@pytest.mark.parametrize(
    "math,math_group_type_index,expected",
    [
        # Count per actor math types should always return False
        (CountPerActorMathType.AVG_COUNT_PER_ACTOR, MathGroupTypeIndex.NUMBER_0, False),
        (CountPerActorMathType.MIN_COUNT_PER_ACTOR, MathGroupTypeIndex.NUMBER_1, False),
        (CountPerActorMathType.MAX_COUNT_PER_ACTOR, MathGroupTypeIndex.NUMBER_2, False),
        (CountPerActorMathType.MEDIAN_COUNT_PER_ACTOR, MathGroupTypeIndex.NUMBER_0, False),
        (CountPerActorMathType.P75_COUNT_PER_ACTOR, MathGroupTypeIndex.NUMBER_1, False),
        (CountPerActorMathType.P90_COUNT_PER_ACTOR, MathGroupTypeIndex.NUMBER_2, False),
        (CountPerActorMathType.P95_COUNT_PER_ACTOR, MathGroupTypeIndex.NUMBER_0, False),
        (CountPerActorMathType.P99_COUNT_PER_ACTOR, MathGroupTypeIndex.NUMBER_1, False),
        # Count per actor without group index
        (CountPerActorMathType.AVG_COUNT_PER_ACTOR, None, False),
        (CountPerActorMathType.MAX_COUNT_PER_ACTOR, None, False),
    ],
)
def test_is_groups_math_count_per_actor(math, math_group_type_index, expected):
    """Test is_groups_math with count per actor math types (should always be False)."""
    series = EventsNode(event="$pageview", math=math, math_group_type_index=math_group_type_index)
    assert is_groups_math(series) == expected


def test_is_groups_math_mixed_conditions():
    """Test edge case: property math with group index should still return False."""
    series = EventsNode(
        event="$pageview",
        math=PropertyMathType.AVG,
        math_property="$session_duration",
        math_group_type_index=MathGroupTypeIndex.NUMBER_0,
    )
    assert is_groups_math(series) is False


def test_is_groups_math_with_additional_properties():
    """Test that additional properties don't affect the result."""
    series = EventsNode(
        event="$pageview",
        math="unique_group",
        math_group_type_index=MathGroupTypeIndex.NUMBER_1,
        properties=[],  # Additional properties shouldn't affect result
    )
    assert is_groups_math(series) is True
