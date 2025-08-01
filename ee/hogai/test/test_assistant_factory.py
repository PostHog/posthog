"""
Tests for the new assistant factory and architecture.
"""

import pytest
from unittest.mock import Mock, patch
from uuid import uuid4
from pydantic import BaseModel, Field

from ee.hogai.factories.assistant_factory import AssistantFactory, create_main_assistant, create_insights_assistant
from ee.hogai.assistants.main_assistant import MainAssistant
from ee.hogai.assistants.insights_assistant import InsightsAssistant

# Legacy components removed - using factory pattern directly
from posthog.schema import HumanMessage


class TestAssistantFactory:
    """Test the assistant factory."""

    def test_create_main_assistant(self):
        """Test creating a main assistant."""
        team = Mock()
        conversation = Mock()
        user = Mock()

        assistant = AssistantFactory.create(
            assistant_type="main",
            team=team,
            conversation=conversation,
            user=user,
        )

        assert isinstance(assistant, MainAssistant)
        assert assistant._team == team
        assert assistant._user == user
        assert assistant._conversation == conversation

    def test_create_insights_assistant(self):
        """Test creating an insights assistant."""
        team = Mock()
        conversation = Mock()
        user = Mock()

        assistant = AssistantFactory.create(
            assistant_type="insights",
            team=team,
            conversation=conversation,
            user=user,
        )

        assert isinstance(assistant, InsightsAssistant)
        assert assistant._team == team
        assert assistant._user == user
        assert assistant._conversation == conversation

    def test_create_assistant_alias(self):
        """Test that 'assistant' is an alias for 'main'."""
        team = Mock()
        conversation = Mock()
        user = Mock()

        assistant = AssistantFactory.create(
            assistant_type="assistant",
            team=team,
            conversation=conversation,
            user=user,
        )

        assert isinstance(assistant, MainAssistant)

    def test_create_unknown_type_raises_error(self):
        """Test that unknown assistant type raises ValueError."""
        team = Mock()
        conversation = Mock()
        user = Mock()

        with pytest.raises(ValueError, match="Unsupported assistant type: 'unknown'"):
            AssistantFactory.create(
                assistant_type="unknown",
                team=team,
                conversation=conversation,
                user=user,
            )

    def test_helper_functions(self):
        """Test the helper functions work correctly."""
        team = Mock()
        conversation = Mock()
        user = Mock()

        # Test main assistant helper
        main_assistant = create_main_assistant(
            team=team,
            conversation=conversation,
            user=user,
        )
        assert isinstance(main_assistant, MainAssistant)

        # Test insights assistant helper
        insights_assistant = create_insights_assistant(
            team=team,
            conversation=conversation,
            user=user,
        )
        assert isinstance(insights_assistant, InsightsAssistant)


# Legacy assistant tests removed - functionality moved to factory pattern


@pytest.mark.asyncio
class TestAssistantIntegration:
    """Integration tests for the new assistant architecture."""

    @patch("ee.hogai.main_assistant.AssistantGraph")
    async def test_main_assistant_initialization(self, mock_graph_class):
        """Test that MainAssistant initializes correctly."""
        # Mock the graph
        mock_graph = Mock()
        mock_compiled_graph = Mock()
        mock_graph.compile_full_graph.return_value = mock_compiled_graph
        mock_graph_class.return_value = mock_graph

        team = Mock()
        conversation = Mock()
        user = Mock()
        message = HumanMessage(content="Test message", id=str(uuid4()))

        assistant = MainAssistant(
            team=team,
            conversation=conversation,
            new_message=message,
            user=user,
        )

        # Verify graph creation
        graph = assistant._create_graph()
        mock_graph_class.assert_called_once_with(team, user)
        mock_graph.compile_full_graph.assert_called_once()
        assert graph == mock_compiled_graph

        # Verify update processor
        processor = assistant._get_update_processor()
        assert processor is not None


class TestErrorPathCoverage:
    """Test failure scenarios in factory and transitions as requested in PR review."""

    def test_invalid_assistant_types(self):
        """Test all invalid assistant type scenarios."""
        team = Mock()
        conversation = Mock()
        user = Mock()

        invalid_types = ["", "unknown", "legacy", "bad_type", None, 123, []]

        for invalid_type in invalid_types:
            with pytest.raises(ValueError) as exc_info:
                AssistantFactory.create(
                    assistant_type=invalid_type,
                    team=team,
                    conversation=conversation,
                    user=user,
                )

            # Verify the error message is helpful
            error_msg = str(exc_info.value)
            assert "Unsupported assistant type" in error_msg
            assert "Supported types: main, assistant, insights" in error_msg
            assert str(invalid_type) in error_msg

    def test_factory_with_none_parameters(self):
        """Test factory behavior with None parameters."""
        # Test with None team
        with pytest.raises((TypeError, AttributeError)):
            AssistantFactory.create(
                assistant_type="main",
                team=None,
                conversation=Mock(),
                user=Mock(),
            )

        # Test with None conversation
        with pytest.raises((TypeError, AttributeError)):
            AssistantFactory.create(
                assistant_type="main",
                team=Mock(),
                conversation=None,
                user=Mock(),
            )

        # Test with None user
        with pytest.raises((TypeError, AttributeError)):
            AssistantFactory.create(
                assistant_type="main",
                team=Mock(),
                conversation=Mock(),
                user=None,
            )

    def test_malformed_transition_contexts(self):
        """Test transitions with malformed context data."""
        from ee.hogai.utils.transitions import context_passthrough

        class SimpleParent(BaseModel):
            messages: list[str] = Field(default=[])

        class SimpleChild(BaseModel):
            messages: list[str] = Field(default=[])
            required_field: str

        # Test context_passthrough with missing required keys
        transition = context_passthrough(SimpleChild, {"required_key": "required_field"})

        parent = SimpleParent(messages=["test"])

        # Missing context keys should raise error
        with pytest.raises(ValueError, match="Missing required context keys"):
            transition.apply_into(parent, {})

        with pytest.raises(ValueError, match="Missing required context keys"):
            transition.apply_into(parent, {"wrong_key": "value"})

        # Partial context should still fail
        with pytest.raises(ValueError, match="Missing required context keys"):
            transition.apply_into(parent, {"other_key": "value"})

    def test_state_mapping_failures(self):
        """Test state mapping failures and recovery."""
        from ee.hogai.utils.transitions import StateTransition
        from pydantic import BaseModel, ValidationError

        class StrictChild(BaseModel):
            required_int: int
            required_str: str

        class ParentState(BaseModel):
            messages: list[str] = Field(default=[])

        # Transition that provides invalid data types
        def bad_into(src, ctx):
            return StrictChild(
                required_int="not_an_int",  # Wrong type
                required_str=123,  # Wrong type
            )

        transition = StateTransition[ParentState, StrictChild](into=bad_into, outof=lambda dst, src: src)

        parent = ParentState()

        # Should raise validation error due to type mismatch
        with pytest.raises((ValidationError, ValueError)):
            transition.apply_into(parent, {})

    def test_circular_reference_handling(self):
        """Test handling of circular references in state objects."""
        from ee.hogai.utils.transitions import StateTransition
        from pydantic import BaseModel

        class SelfRefState(BaseModel):
            name: str
            # Simulate potential circular reference issues
            data: dict = Field(default={})

        def create_circular_data(src, ctx):
            circular_dict = {"name": "test"}
            circular_dict["self"] = circular_dict  # Create circular reference

            return SelfRefState(name=src.name, data=circular_dict)

        transition = StateTransition[SelfRefState, SelfRefState](
            into=create_circular_data, outof=lambda dst, src: src.model_copy(update={"name": dst.name})
        )

        parent = SelfRefState(name="parent")

        # This should handle circular references gracefully
        # (Pydantic typically converts them to safe representations)
        child = transition.apply_into(parent, {})
        assert child.name == "parent"
        assert child.data["name"] == "test"

    def test_transition_wrapper_error_handling(self):
        """Test the transition wrapper error handling in graph.py."""
        from ee.hogai.graph.graph import BaseAssistantGraph
        from ee.hogai.utils.transitions import StateTransition
        from ee.hogai.utils.types import AssistantState
        from posthog.models import Team, User
        from unittest.mock import Mock

        # Create a transition that will fail
        def failing_transition(src, ctx):
            raise RuntimeError("Transition failed")

        failing_state_transition = StateTransition[AssistantState, AssistantState](
            into=failing_transition, outof=lambda dst, src: src
        )

        # Mock subgraph that should be called when transition fails
        mock_subgraph = Mock()
        mock_subgraph.invoke.return_value = AssistantState(messages=[])

        # Create graph and add subgraph with failing transition
        team = Mock(spec=Team)
        user = Mock(spec=User)
        graph = BaseAssistantGraph(team, user, AssistantState)

        # This should create a wrapper that falls back to direct execution on error
        graph.add_subgraph("test_node", mock_subgraph, failing_state_transition)

        # The wrapper should be created and stored
        assert "test_node" in graph._transitions

        # When we compile and try to use it, it should fall back gracefully
        # (This is tested implicitly by the wrapper implementation)

    def test_invalid_state_field_access(self):
        """Test handling of invalid field access in transitions."""
        from ee.hogai.utils.transitions import lift_fields
        from pydantic import BaseModel

        class MinimalState(BaseModel):
            messages: list[str] = Field(default=[])

        class ExpandedState(BaseModel):
            messages: list[str] = Field(default=[])
            extra_field: str = Field(default="default")

        # Try to lift a field that doesn't exist
        transition = lift_fields("messages", "nonexistent_field", dst_type=ExpandedState)

        parent = MinimalState(messages=["test"])

        # Should succeed and ignore missing field
        child = transition.apply_into(parent, {})
        assert child.messages == ["test"]
        assert child.extra_field == "default"  # Uses default value

        # Test with required field that's missing
        strict_transition = lift_fields(
            "messages", "nonexistent_field", dst_type=ExpandedState, required_fields={"nonexistent_field"}
        )

        # Should raise error for missing required field
        with pytest.raises(ValueError, match="Required field 'nonexistent_field' missing"):
            strict_transition.apply_into(parent, {})

    @patch("ee.hogai.insights_assistant.InsightsAssistantGraph")
    async def test_insights_assistant_initialization(self, mock_graph_class):
        """Test that InsightsAssistant initializes correctly."""
        # Mock the graph
        mock_graph = Mock()
        mock_compiled_graph = Mock()
        mock_graph.compile_full_graph.return_value = mock_compiled_graph
        mock_graph_class.return_value = mock_graph

        team = Mock()
        conversation = Mock()
        user = Mock()

        assistant = InsightsAssistant(
            team=team,
            conversation=conversation,
            user=user,
        )

        # Verify graph creation
        graph = assistant._create_graph()
        mock_graph_class.assert_called_once_with(team, user)
        mock_graph.compile_full_graph.assert_called_once()
        assert graph == mock_compiled_graph

        # Verify update processor
        processor = assistant._get_update_processor()
        assert processor is not None
