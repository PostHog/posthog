import pytest
from posthog.hogql_queries.insights.trends.utils import get_properties_chain
from posthog.schema import BreakdownType


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
