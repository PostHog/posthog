import operator
from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Optional, Union

from langchain_core.agents import AgentAction
from langchain_core.messages import BaseMessage as LangchainBaseMessage
from langgraph.graph import END, START
from pydantic import BaseModel, Field

from posthog.schema import (
    AssistantMessage,
    AssistantToolCallMessage,
    FailureMessage,
    HumanMessage,
    ReasoningMessage,
    VisualizationMessage,
)

AIMessageUnion = Union[
    AssistantMessage, VisualizationMessage, FailureMessage, ReasoningMessage, AssistantToolCallMessage
]
AssistantMessageUnion = Union[HumanMessage, AIMessageUnion]


class _SharedAssistantState(BaseModel):
    """
    The state of the root node.
    """

    intermediate_steps: Optional[list[tuple[AgentAction, Optional[str]]]] = Field(default=None)
    start_id: Optional[str] = Field(default=None)
    """
    The ID of the message from which the conversation started.
    """
    plan: Optional[str] = Field(default=None)
    resumed: Optional[bool] = Field(default=None)
    """
    Whether the agent was resumed after interruption, such as a human in the loop.
    """
    memory_updated: Optional[bool] = Field(default=None)
    """
    Whether the memory was updated in the `MemoryCollectorNode`.
    """
    memory_collection_messages: Optional[Sequence[LangchainBaseMessage]] = Field(default=None)
    """
    The messages with tool calls to collect memory in the `MemoryCollectorToolsNode`.
    """
    root_tool_call_id: Optional[str] = Field(default=None)
    """
    The ID of the tool call from the root node.
    """
    root_tool_insight_plan: Optional[str] = Field(default=None)
    """
    The insight plan to generate.
    """
    root_tool_insight_type: Optional[str] = Field(default=None)
    """
    The type of insight to generate.
    """


class AssistantState(_SharedAssistantState):
    messages: Annotated[Sequence[AssistantMessageUnion], operator.add]
    """
    Messages exposed to the user.
    """


class PartialAssistantState(_SharedAssistantState):
    messages: Optional[Sequence[AssistantMessageUnion]] = Field(default=None)
    """
    Messages exposed to the user.
    """


class AssistantNodeName(StrEnum):
    START = START
    END = END
    MEMORY_ONBOARDING = "memory_onboarding"
    MEMORY_INITIALIZER = "memory_initializer"
    MEMORY_INITIALIZER_INTERRUPT = "memory_initializer_interrupt"
    ROOT = "root"
    ROOT_TOOLS = "root_tools"
    TRENDS_PLANNER = "trends_planner"
    TRENDS_PLANNER_TOOLS = "trends_planner_tools"
    TRENDS_GENERATOR = "trends_generator"
    TRENDS_GENERATOR_TOOLS = "trends_generator_tools"
    FUNNEL_PLANNER = "funnel_planner"
    FUNNEL_PLANNER_TOOLS = "funnel_planner_tools"
    FUNNEL_GENERATOR = "funnel_generator"
    FUNNEL_GENERATOR_TOOLS = "funnel_generator_tools"
    RETENTION_PLANNER = "retention_planner"
    RETENTION_PLANNER_TOOLS = "retention_planner_tools"
    RETENTION_GENERATOR = "retention_generator"
    RETENTION_GENERATOR_TOOLS = "retention_generator_tools"
    QUERY_EXECUTOR = "query_executor"
    MEMORY_COLLECTOR = "memory_collector"
    MEMORY_COLLECTOR_TOOLS = "memory_collector_tools"
