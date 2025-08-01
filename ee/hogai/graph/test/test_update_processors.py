"""
Tests for graph update processors.
"""

import pytest
from unittest.mock import Mock

from ee.hogai.graph.insights_update_processor import InsightsUpdateProcessor
from ee.hogai.graph.assistant_update_processor import AssistantUpdateProcessor
from ee.hogai.utils.graph_states import InsightsGraphState, AssistantGraphState
from ee.hogai.utils.types import AssistantNodeName
from posthog.schema import AssistantMessage, AssistantToolCall


@pytest.mark.asyncio
class TestInsightsUpdateProcessor:
    """Test the insights graph update processor."""

    async def test_trends_generator_reasoning(self):
        """Test reasoning message for trends generator."""
        processor = InsightsUpdateProcessor(Mock(), Mock())
        state = InsightsGraphState(messages=[])

        result = await processor.get_reasoning_message(AssistantNodeName.TRENDS_GENERATOR, state)

        assert result is not None
        assert result.content == "Creating trends query"

    async def test_query_planner_reasoning_with_steps(self):
        """Test query planner reasoning with intermediate steps."""
        from langchain_core.agents import AgentAction

        processor = InsightsUpdateProcessor(Mock(), Mock())

        # Mock intermediate steps
        action = AgentAction(tool="retrieve_event_properties", tool_input={"event_name": "page_view"}, log="")

        state = InsightsGraphState(messages=[], intermediate_steps=[(action, None)])

        result = await processor.get_reasoning_message(AssistantNodeName.QUERY_PLANNER, state)

        assert result is not None
        assert result.content == "Picking relevant events and properties"
        assert len(result.substeps) == 1
        assert "Exploring `page_view` event's properties" in result.substeps[0]

    async def test_unknown_node_returns_none(self):
        """Test that unknown nodes return None."""
        processor = InsightsUpdateProcessor(Mock(), Mock())
        state = InsightsGraphState(messages=[])

        result = await processor.get_reasoning_message("unknown_node", state)

        assert result is None


class TestAssistantUpdateProcessor:
    """Test the main assistant graph update processor."""

    async def test_root_tools_reasoning_with_insight_tool(self):
        """Test root tools reasoning with insight tool call."""
        processor = AssistantUpdateProcessor(Mock(), Mock())

        tool_call = AssistantToolCall(id="123", name="create_and_query_insight", args={})

        message = AssistantMessage(content="Let me create an insight", tool_calls=[tool_call])

        state = AssistantGraphState(messages=[message])

        result = await processor.get_reasoning_message(AssistantNodeName.ROOT_TOOLS, state)

        assert result is not None
        assert result.content == "Coming up with an insight"

    async def test_root_tools_reasoning_no_tool_calls(self):
        """Test root tools reasoning with no tool calls."""
        processor = AssistantUpdateProcessor(Mock(), Mock())

        message = AssistantMessage(content="Just a message")
        state = AssistantGraphState(messages=[message])

        result = await processor.get_reasoning_message(AssistantNodeName.ROOT_TOOLS, state)

        assert result is None

    async def test_memory_initializer_reasoning(self):
        """Test memory initializer reasoning."""
        processor = AssistantUpdateProcessor(Mock(), Mock())
        state = AssistantGraphState(messages=[])

        result = await processor.get_reasoning_message(AssistantNodeName.MEMORY_INITIALIZER, state)

        assert result is not None
        assert result.content == "Setting up conversation context"
