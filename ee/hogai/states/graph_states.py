"""
Graph-specific state classes for the AI Assistant.

This module defines state classes for each graph type, replacing the monolithic AssistantState.
Each graph has its own state with only the fields it needs.
"""

from typing import Annotated, Literal, Optional
from collections.abc import Sequence
from langchain_core.messages import BaseMessage as LangchainBaseMessage
from pydantic import Field

from ee.hogai.utils.types import (
    AssistantMessageUnion,
    BaseState,
    IntermediateStep,
    add_and_merge_messages,
    merge,
    merge_retry_counts,
)


class BaseGraphState(BaseState):
    """Base state containing only truly shared fields across all graphs."""

    messages: Annotated[Sequence[AssistantMessageUnion], add_and_merge_messages] = Field(default=[])
    """Messages exposed to the user."""

    graph_status: Optional[Literal["resumed", "interrupted", ""]] = Field(default=None)
    """Whether the graph was interrupted or resumed."""

    query_generation_retry_count: Annotated[int, merge_retry_counts] = Field(default=0)
    """Tracks the number of times the query generation has been retried."""


class AssistantGraphState(BaseGraphState):
    """State for the main assistant graph."""

    @staticmethod
    def _get_ignored_reset_fields() -> set[str]:
        """Fields to ignore during state resets due to race conditions."""
        return {"memory_collection_messages"}

    start_id: Optional[str] = Field(default=None)
    """The ID of the message from which the conversation started."""

    root_conversation_start_id: Optional[str] = Field(default=None)
    """The ID of the message to start from to keep the message window short enough."""

    root_tool_call_id: Optional[str] = Field(default=None)
    """The ID of the tool call from the root node."""

    root_tool_calls_count: Optional[int] = Field(default=None)
    """Tracks the number of tool calls made by the root node to terminate the loop."""

    memory_collection_messages: Annotated[Optional[Sequence[LangchainBaseMessage]], merge] = Field(default=None)
    """The messages with tool calls to collect memory in the MemoryCollectorToolsNode."""

    onboarding_question: Optional[str] = Field(default=None)
    """A clarifying question asked during the onboarding process."""

    search_insights_query: Optional[str] = Field(default=None)
    """The user's search query for finding existing insights."""


class InsightsGraphState(BaseGraphState):
    """State for the insights subgraph."""

    intermediate_steps: Optional[list[IntermediateStep]] = Field(default=None)
    """Actions taken by the query planner agent."""

    plan: Optional[str] = Field(default=None)
    """The insight generation plan."""

    root_tool_insight_plan: Optional[str] = Field(default=None)
    """The insight plan to generate (passed from parent graph)."""

    root_tool_insight_type: Optional[str] = Field(default=None)
    """The type of insight to generate (passed from parent graph)."""

    query_planner_previous_response_id: Optional[str] = Field(default=None)
    """The ID of the previous OpenAI Responses API response made by the query planner."""

    rag_context: Optional[str] = Field(default=None)
    """The context for taxonomy agent."""


# Partial state classes for updates
# These classes represent the same data structure as their main counterparts
# but without field annotations that cause automatic merging behavior


class PartialAssistantGraphState(AssistantGraphState):
    """Partial state for updating AssistantGraphState without merging messages."""

    # Override only the fields that need different behavior for partial updates
    messages: Sequence[AssistantMessageUnion] = Field(default=[])
    """Messages (non-merging for partial updates)."""

    memory_collection_messages: Optional[Sequence[LangchainBaseMessage]] = Field(default=None)
    """Memory collection messages (non-merging for partial updates)."""


class PartialInsightsGraphState(InsightsGraphState):
    """Partial state for updating InsightsGraphState without merging messages."""

    # Override only the fields that need different behavior for partial updates
    messages: Sequence[AssistantMessageUnion] = Field(default=[])
    """Messages (non-merging for partial updates)."""
