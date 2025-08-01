"""
Test streaming behavior with state transitions.
"""

import pytest
from unittest.mock import Mock, AsyncMock

from ee.hogai.graph.graph import BaseAssistantGraph
from ee.hogai.utils.transitions import StateTransition
from ee.hogai.utils.graph_states import AssistantGraphState, InsightsGraphState
from posthog.schema import HumanMessage


class TestStreamingTransitions:
    """Test that state transitions preserve streaming behavior."""

    @pytest.mark.asyncio
    async def test_transition_wrapper_preserves_streaming(self):
        """Test that the transition wrapper properly streams updates."""
        team = Mock()
        user = Mock()

        # Create a mock subgraph with streaming capability
        mock_subgraph = AsyncMock()

        # Create messages
        msg1 = HumanMessage(content="message1")
        msg2 = HumanMessage(content="message2")
        msg3 = HumanMessage(content="message3")
        initial_msg = HumanMessage(content="initial")

        # Create an async generator for streaming
        async def mock_stream(state):
            # Simulate streaming updates
            yield InsightsGraphState(messages=[msg1])
            yield InsightsGraphState(messages=[msg1, msg2])
            yield InsightsGraphState(messages=[msg1, msg2, msg3])

        mock_subgraph.astream = mock_stream

        # Create a transition
        transition = StateTransition[AssistantGraphState, InsightsGraphState](
            into=lambda src, ctx: InsightsGraphState(messages=src.messages),
            outof=lambda dst, src: src.model_copy(update={"messages": dst.messages}),
        )

        # Create the graph
        graph = BaseAssistantGraph(team, user, AssistantGraphState)

        # Create the transition wrapper
        wrapper = graph._create_transition_wrapper(mock_subgraph, transition)

        # Test streaming through the wrapper
        parent_state = AssistantGraphState(messages=[initial_msg])
        updates = []

        async for update in wrapper(parent_state):
            updates.append(update)

        # Verify we got streaming updates
        assert len(updates) == 3
        assert len(updates[0].messages) == 1
        assert updates[0].messages[0].content == "message1"
        assert len(updates[1].messages) == 2
        assert updates[1].messages[1].content == "message2"
        assert len(updates[2].messages) == 3
        assert updates[2].messages[2].content == "message3"

    @pytest.mark.asyncio
    async def test_transition_wrapper_fallback_non_streaming(self):
        """Test that the transition wrapper falls back to non-streaming when needed."""
        team = Mock()
        user = Mock()

        # Create messages
        initial_msg = HumanMessage(content="initial")
        final_msg = HumanMessage(content="final_result")

        # Create a mock subgraph without streaming capability
        mock_subgraph = AsyncMock()
        mock_subgraph.astream = None  # No streaming
        mock_subgraph.ainvoke = AsyncMock(return_value=InsightsGraphState(messages=[final_msg]))

        # Create a transition
        transition = StateTransition[AssistantGraphState, InsightsGraphState](
            into=lambda src, ctx: InsightsGraphState(messages=src.messages),
            outof=lambda dst, src: src.model_copy(update={"messages": dst.messages}),
        )

        # Create the graph
        graph = BaseAssistantGraph(team, user, AssistantGraphState)

        # Create the transition wrapper
        wrapper = graph._create_transition_wrapper(mock_subgraph, transition)

        # Test non-streaming execution
        parent_state = AssistantGraphState(messages=[initial_msg])

        # Since it's an async generator, we need to iterate through it
        results = []
        async for result in wrapper(parent_state):
            results.append(result)

        # Verify we got the final result
        assert len(results) == 1
        assert len(results[0].messages) == 1
        assert results[0].messages[0].content == "final_result"
        mock_subgraph.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_transition_wrapper_error_recovery(self):
        """Test that the transition wrapper handles errors gracefully."""
        team = Mock()
        user = Mock()

        # Create a mock subgraph that will fail during transition
        mock_subgraph = AsyncMock()

        async def mock_stream(state):
            yield state  # Just echo the state

        mock_subgraph.astream = mock_stream

        # Create a transition that will fail
        def failing_into(src, ctx):
            raise ValueError("Transition failed")

        transition = StateTransition[AssistantGraphState, InsightsGraphState](
            into=failing_into, outof=lambda dst, src: src
        )

        # Create the graph
        graph = BaseAssistantGraph(team, user, AssistantGraphState)

        # Create the transition wrapper
        wrapper = graph._create_transition_wrapper(mock_subgraph, transition)

        # Create message
        initial_msg = HumanMessage(content="initial")

        # Test error recovery - should fall back to direct streaming
        parent_state = AssistantGraphState(messages=[initial_msg])
        updates = []

        async for update in wrapper(parent_state):
            updates.append(update)

        # Should get the original state back (fallback behavior)
        assert len(updates) == 1
        assert updates[0] == parent_state
