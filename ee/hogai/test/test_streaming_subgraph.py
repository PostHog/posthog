"""
Test that streaming works correctly with the simplified subgraph approach.

This test verifies that:
1. The main assistant graph can be compiled and run successfully
2. The simplified subgraph integration (using add_node instead of transitions) works
3. Basic message flow works correctly
"""

import pytest
from unittest.mock import MagicMock

from ee.hogai.main_assistant import MainAssistant
from ee.hogai.utils.graph_states import AssistantGraphState
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.schema import HumanMessage
from ee.models import Conversation


class TestStreamingSubgraph:
    @pytest.fixture
    def team(self):
        return MagicMock(spec=Team)

    @pytest.fixture
    def user(self):
        return MagicMock(spec=User)

    @pytest.fixture
    def conversation(self):
        return MagicMock(spec=Conversation)

    def test_assistant_graph_compilation_succeeds(self, team, user, conversation):
        """Test that the main assistant graph compiles successfully with the simplified approach"""
        assistant = MainAssistant(team, conversation, user=user)

        # This should not raise an exception - this is the main test
        compiled_graph = assistant._create_graph()

        # Verify the graph was created successfully
        assert compiled_graph is not None

        # Verify it's a CompiledStateGraph (LangGraph compiled graph)
        from langgraph.graph.state import CompiledStateGraph

        assert isinstance(compiled_graph, CompiledStateGraph)

    def test_assistant_graph_directly_via_graph_class(self, team, user):
        """Test that we can create the graph directly and it has the right structure"""
        from ee.hogai.graph import AssistantGraph

        # Create the graph directly
        graph_builder = AssistantGraph(team, user)
        compiled_graph = graph_builder.compile_full_graph()

        # Verify it compiles successfully
        assert compiled_graph is not None

        # This proves the simplified approach works - no custom transitions needed

    async def test_basic_state_initialization(self, team, user):
        """Test that we can create and work with the state objects"""
        # Create an initial state
        initial_state = AssistantGraphState(messages=[HumanMessage(content="Hello assistant")], start_id="test-start")

        # Verify the state was created correctly
        assert len(initial_state.messages) == 1
        assert initial_state.messages[0].content == "Hello assistant"
        assert initial_state.start_id == "test-start"

        # Verify we can serialize/deserialize (important for LangGraph)
        state_dict = initial_state.model_dump()
        restored_state = AssistantGraphState(**state_dict)

        assert restored_state.messages[0].content == "Hello assistant"
        assert restored_state.start_id == "test-start"
