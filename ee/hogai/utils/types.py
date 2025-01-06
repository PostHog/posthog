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
    FailureMessage,
    HumanMessage,
    ReasoningMessage,
    RouterMessage,
    VisualizationMessage,
)

AIMessageUnion = Union[AssistantMessage, VisualizationMessage, FailureMessage, RouterMessage, ReasoningMessage]
AssistantMessageUnion = Union[HumanMessage, AIMessageUnion]


class _SharedAssistantState(BaseModel):
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


class AssistantState(_SharedAssistantState):
    messages: Annotated[Sequence[AssistantMessageUnion], operator.add]


class PartialAssistantState(_SharedAssistantState):
    messages: Optional[Sequence[AssistantMessageUnion]] = Field(default=None)


class AssistantNodeName(StrEnum):
    START = START
    END = END
    MEMORY_ONBOARDING = "memory_onboarding"
    MEMORY_INITIALIZER = "memory_initializer"
    MEMORY_INITIALIZER_INTERRUPT = "memory_initializer_interrupt"
    ROUTER = "router"
    TRENDS_PLANNER = "trends_planner"
    TRENDS_PLANNER_TOOLS = "trends_planner_tools"
    TRENDS_GENERATOR = "trends_generator"
    TRENDS_GENERATOR_TOOLS = "trends_generator_tools"
    FUNNEL_PLANNER = "funnel_planner"
    FUNNEL_PLANNER_TOOLS = "funnel_planner_tools"
    FUNNEL_GENERATOR = "funnel_generator"
    FUNNEL_GENERATOR_TOOLS = "funnel_generator_tools"
    SUMMARIZER = "summarizer"
    MEMORY_COLLECTOR = "memory_collector"
    MEMORY_COLLECTOR_TOOLS = "memory_collector_tools"
