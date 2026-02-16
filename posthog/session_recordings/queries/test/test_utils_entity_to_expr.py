from unittest.mock import Mock

from posthog.schema import EventPropertyFilter, EventsNode

from posthog.hogql import ast

from posthog.session_recordings.queries.utils import _entity_to_expr


def test_events_type_with_id_no_properties():
    team = Mock()
    entity = EventsNode(kind="EventsNode", event="test_event", name="test_event")
    result = _entity_to_expr(entity, team)

    # Should return CompareOperation, not And
    assert isinstance(result, ast.CompareOperation)
    assert result.op == ast.CompareOperationOp.Eq
    assert isinstance(result.left, ast.Field)
    assert result.left.chain == ["events", "event"]
    assert isinstance(result.right, ast.Constant)
    assert result.right.value == "test_event"


def test_events_type_with_id_and_fixed_properties():
    team = Mock()
    entity = EventsNode(
        kind="EventsNode",
        event="test_event",
        name="test_event",
        fixedProperties=[EventPropertyFilter(key="prop", value="val", operator="exact", type="event")],
    )
    result = _entity_to_expr(entity, team)

    assert isinstance(result, ast.And)
    assert len(result.exprs) == 2


def test_all_events_no_properties():
    team = Mock()
    entity = EventsNode(kind="EventsNode", event=None)
    result = _entity_to_expr(entity, team)

    assert isinstance(result, ast.Constant)
    assert result.value is True
