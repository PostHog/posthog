import uuid
from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Literal, Optional, Union

from langchain_core.agents import AgentAction
from langchain_core.messages import BaseMessage as LangchainBaseMessage
from langgraph.graph import END, START
from pydantic import BaseModel, Field

from ee.models import Conversation
from posthog.schema import (
    AssistantEventType,
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

AssistantOutput = (
    tuple[Literal[AssistantEventType.CONVERSATION], Conversation]
    | tuple[Literal[AssistantEventType.MESSAGE], AssistantMessageUnion]
)


def add_and_merge_messages(
    left: Sequence[AssistantMessageUnion], right: Sequence[AssistantMessageUnion]
) -> Sequence[AssistantMessageUnion]:
    """Merges two lists of messages, updating existing messages by ID.

    By default, this ensures the state is "append-only", unless the
    new message has the same ID as an existing message.

    Args:
        left: The base list of messages.
        right: The list of messages to merge
            into the base list.

    Returns:
        A new list of messages with the messages from `right` merged into `left`.
        If a message in `right` has the same ID as a message in `left`, the
        message from `right` will replace the message from `left`.
    """
    # coerce to list
    left = list(left)
    right = list(right)

    # assign missing ids
    for m in left:
        if m.id is None:
            m.id = str(uuid.uuid4())
    for m in right:
        if m.id is None:
            m.id = str(uuid.uuid4())

    # merge
    left_idx_by_id = {m.id: i for i, m in enumerate(left)}
    merged = left.copy()
    for m in right:
        if (existing_idx := left_idx_by_id.get(m.id)) is not None:
            merged[existing_idx] = m
        else:
            merged.append(m)

    return merged


def merge_retry_counts(left: int, right: int) -> int:
    """Merges two retry counts by taking the maximum value.

    Args:
        left: The base retry count
        right: The new retry count

    Returns:
        The maximum of the two counts
    """
    return max(left, right)


class _SharedAssistantState(BaseModel):
    """
    The state of the root node.
    """

    start_id: Optional[str] = Field(default=None)
    """
    The ID of the message from which the conversation started.
    """
    graph_status: Optional[Literal["resumed", "interrupted", ""]] = Field(default=None)
    """
    Whether the graph was interrupted or resumed.
    """

    intermediate_steps: Optional[list[tuple[AgentAction, Optional[str]]]] = Field(default=None)
    """
    Actions taken by the ReAct agent.
    """
    plan: Optional[str] = Field(default=None)
    """
    The insight generation plan.
    """

    onboarding_question: Optional[str] = Field(default=None)
    """
    A clarifying question asked during the onboarding process.
    """

    memory_updated: Optional[bool] = Field(default=None)
    """
    Whether the memory was updated in the `MemoryCollectorNode`.
    """
    memory_collection_messages: Optional[Sequence[LangchainBaseMessage]] = Field(default=None)
    """
    The messages with tool calls to collect memory in the `MemoryCollectorToolsNode`.
    """

    root_conversation_start_id: Optional[str] = Field(default=None)
    """
    The ID of the message to start from to keep the message window short enough.
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
    root_tool_calls_count: Optional[int] = Field(default=None)
    """
    Tracks the number of tool calls made by the root node to terminate the loop.
    """
    rag_context: Optional[str] = Field(default=None)
    """
    The context for taxonomy agent.
    """
    query_generation_retry_count: Annotated[int, merge_retry_counts] = Field(default=0)
    """
    Tracks the number of times the query generation has been retried.
    """


class AssistantState(_SharedAssistantState):
    messages: Annotated[Sequence[AssistantMessageUnion], add_and_merge_messages]
    """
    Messages exposed to the user.
    """


class PartialAssistantState(_SharedAssistantState):
    messages: Sequence[AssistantMessageUnion] = Field(default=[])
    """
    Messages exposed to the user.
    """

    @classmethod
    def get_reset_state(cls) -> "PartialAssistantState":
        return cls(
            intermediate_steps=[],
            plan="",
            graph_status="",
            memory_updated=False,
            memory_collection_messages=[],
            root_tool_call_id="",
            root_tool_insight_plan="",
            root_tool_insight_type="",
            root_tool_calls_count=0,
            root_conversation_start_id="",
            rag_context="",
            query_generation_retry_count=0,
        )


class AssistantNodeName(StrEnum):
    START = START
    END = END
    BILLING = "billing"
    MEMORY_INITIALIZER = "memory_initializer"
    MEMORY_INITIALIZER_INTERRUPT = "memory_initializer_interrupt"
    MEMORY_ONBOARDING = "memory_onboarding"
    MEMORY_ONBOARDING_ENQUIRY = "memory_onboarding_enquiry"
    MEMORY_ONBOARDING_ENQUIRY_INTERRUPT = "memory_onboarding_enquiry_interrupt"
    MEMORY_ONBOARDING_FINALIZE = "memory_onboarding_finalize"
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
    SQL_PLANNER = "sql_planner"
    SQL_PLANNER_TOOLS = "sql_planner_tools"
    SQL_GENERATOR = "sql_generator"
    SQL_GENERATOR_TOOLS = "sql_generator_tools"
    QUERY_EXECUTOR = "query_executor"
    MEMORY_COLLECTOR = "memory_collector"
    MEMORY_COLLECTOR_TOOLS = "memory_collector_tools"
    INKEEP_DOCS = "inkeep_docs"
    INSIGHT_RAG_CONTEXT = "insight_rag_context"
    INSIGHTS_SUBGRAPH = "insights_subgraph"
    TITLE_GENERATOR = "title_generator"


class AssistantMode(StrEnum):
    ASSISTANT = "assistant"
    INSIGHTS_TOOL = "insights_tool"
