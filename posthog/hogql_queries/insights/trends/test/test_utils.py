import pytest
from posthog.hogql_queries.insights.trends.utils import get_properties_chain


def test_properties_chain_person():
    p1 = get_properties_chain(breakdown_type="person", breakdown_field="field", group_type_index=None)
    assert p1 == ["person", "properties", "field"]

    p2 = get_properties_chain(breakdown_type="person", breakdown_field="field", group_type_index=1)
    assert p2 == ["person", "properties", "field"]


def test_properties_chain_session():
    p1 = get_properties_chain(breakdown_type="session", breakdown_field="anything", group_type_index=None)
    assert p1 == ["session", "duration"]

    p2 = get_properties_chain(breakdown_type="session", breakdown_field="", group_type_index=None)
    assert p2 == ["session", "duration"]

    p3 = get_properties_chain(breakdown_type="session", breakdown_field="", group_type_index=1)
    assert p3 == ["session", "duration"]


def test_properties_chain_groups():
    p1 = get_properties_chain(breakdown_type="group", breakdown_field="anything", group_type_index=1)
    assert p1 == ["group_1", "properties", "anything"]

    with pytest.raises(Exception) as e:
        get_properties_chain(breakdown_type="group", breakdown_field="anything", group_type_index=None)
        assert "group_type_index missing from params" in str(e.value)


def test_properties_chain_events():
    p1 = get_properties_chain(breakdown_type="event", breakdown_field="anything", group_type_index=None)
    assert p1 == ["properties", "anything"]

    p2 = get_properties_chain(breakdown_type="event", breakdown_field="anything_else", group_type_index=1)
    assert p2 == ["properties", "anything_else"]
