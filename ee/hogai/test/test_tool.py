from typing import Any
from unittest.mock import Mock
from ee.hogai.tool import MaxTool
from ee.hogai.utils.types import AssistantState, AssistantMessage, AssistantToolCallMessage
from posthog.models import Team, User
from uuid import uuid4


class TestMaxTool(MaxTool):
    """Test tool to verify state behavior."""

    name: str = "search_session_recordings"
    description: str = "Test tool for state verification"
    thinking_message: str = "Testing"
    root_system_prompt_template: str = "Test context: {test_var}"
    args_schema: type = None

    async def _arun_impl(self, *args, **kwargs) -> tuple[str, Any]:
        # Add a message to the tool's state
        tool_message = AssistantToolCallMessage(
            content="Test message from tool",
            ui_payload={"test_tool": {"result": "success"}},
            id=str(uuid4()),
            tool_call_id="test_call_id",
            visible=True,
        )
        self._state.messages.append(tool_message)

        return "", {"result": "success"}


def test_max_tool_state_deep_copy():
    """Test that MaxTool creates a deep copy of state and doesn't modify the original."""
    # Create original state with some messages
    original_message = AssistantMessage(
        content="Original message",
        id=str(uuid4()),
    )
    original_state = AssistantState(messages=[original_message])

    # Create a mock team and user
    mock_team = Mock(spec=Team)
    mock_user = Mock(spec=User)

    # Create tool with the original state
    tool = TestMaxTool(team=mock_team, user=mock_user, state=original_state)

    # Verify the tool has its own copy of the state
    assert tool._state is not original_state
    assert tool._state.messages is not original_state.messages

    # Verify the initial state is the same
    assert len(tool._state.messages) == len(original_state.messages)
    assert tool._state.messages[0].content == original_state.messages[0].content

    # Modify the tool's state
    tool_message = AssistantToolCallMessage(
        content="Tool added message",
        ui_payload={"test": "data"},
        id=str(uuid4()),
        tool_call_id="test_id",
        visible=True,
    )
    tool._state.messages.append(tool_message)

    # Verify the tool's state was modified
    assert len(tool._state.messages) == 2
    assert tool._state.messages[1].content == "Tool added message"

    # Verify the original state was NOT modified
    assert len(original_state.messages) == 1
    assert original_state.messages[0].content == "Original message"

    # Verify the original state's message is still the same object
    assert original_state.messages[0] is original_message


def test_max_tool_state_without_initial_state():
    """Test that MaxTool creates a new state when none is provided."""
    mock_team = Mock(spec=Team)
    mock_user = Mock(spec=User)

    # Create tool without initial state
    tool = TestMaxTool(team=mock_team, user=mock_user, state=None)

    # Verify it has a new empty state
    assert isinstance(tool._state, AssistantState)
    assert len(tool._state.messages) == 0

    # Verify we can modify it
    tool._state.messages.append(AssistantMessage(content="Test", id=str(uuid4())))
    assert len(tool._state.messages) == 1


def test_max_tool_state_nested_modifications():
    """Test that deep copy works for nested modifications."""
    # Create original state with nested data
    original_message = AssistantMessage(
        content="Original",
        id=str(uuid4()),
    )
    original_state = AssistantState(messages=[original_message])

    mock_team = Mock(spec=Team)
    mock_user = Mock(spec=User)

    # Create tool
    tool = TestMaxTool(team=mock_team, user=mock_user, state=original_state)

    # Modify nested properties of the tool's state
    tool._state.messages[0].content = "Modified by tool"

    # Verify tool's state was modified
    assert tool._state.messages[0].content == "Modified by tool"

    # Verify original state was NOT modified
    assert original_state.messages[0].content == "Original"
    assert original_message.content == "Original"


def test_max_tool_state_complex_structure():
    """Test that deep copy works for complex nested structures."""
    # Create a complex state with multiple message types
    messages = [
        AssistantMessage(content="Message 1", id=str(uuid4())),
        AssistantToolCallMessage(
            content="Tool message",
            ui_payload={"key": "value"},
            id=str(uuid4()),
            tool_call_id="call_1",
            visible=True,
        ),
    ]
    original_state = AssistantState(messages=messages)

    mock_team = Mock(spec=Team)
    mock_user = Mock(spec=User)

    # Create tool
    tool = TestMaxTool(team=mock_team, user=mock_user, state=original_state)

    # Verify deep copy worked for complex structure - check content equality
    assert len(tool._state.messages) == len(original_state.messages)
    assert tool._state.messages[0].content == original_state.messages[0].content
    assert tool._state.messages[1].content == original_state.messages[1].content
    assert tool._state.messages[1].ui_payload == original_state.messages[1].ui_payload

    # Verify they are different objects (deep copy)
    assert tool._state is not original_state
    assert tool._state.messages is not original_state.messages
    assert tool._state.messages[0] is not original_state.messages[0]
    assert tool._state.messages[1] is not original_state.messages[1]

    # Modify tool's state
    tool._state.messages[1].ui_payload["new_key"] = "new_value"

    # Verify original wasn't affected
    assert "new_key" not in original_state.messages[1].ui_payload
    assert "new_key" in tool._state.messages[1].ui_payload
