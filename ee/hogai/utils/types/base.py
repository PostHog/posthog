import uuid
from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Any, Literal, Optional, Self, TypeVar, Union

from langchain_core.agents import AgentAction
from langchain_core.messages import BaseMessage as LangchainBaseMessage
from langgraph.graph import END, START
from pydantic import BaseModel, Field

from posthog.schema import (
    AssistantEventType,
    AssistantFunnelsQuery,
    AssistantGenerationStatusEvent,
    AssistantHogQLQuery,
    AssistantMessage,
    AssistantRetentionQuery,
    AssistantToolCallMessage,
    AssistantTrendsQuery,
    FailureMessage,
    FunnelsQuery,
    HogQLQuery,
    HumanMessage,
    MultiVisualizationMessage,
    NotebookUpdateMessage,
    PlanningMessage,
    ReasoningMessage,
    RetentionQuery,
    TaskExecutionMessage,
    TrendsQuery,
    VisualizationMessage,
)

from ee.models import Conversation

AIMessageUnion = Union[
    AssistantMessage,
    VisualizationMessage,
    FailureMessage,
    ReasoningMessage,
    AssistantToolCallMessage,
    PlanningMessage,
    TaskExecutionMessage,
    MultiVisualizationMessage,
]
AssistantMessageUnion = Union[HumanMessage, AIMessageUnion, NotebookUpdateMessage]
AssistantMessageOrStatusUnion = Union[AssistantMessageUnion, AssistantGenerationStatusEvent]

AssistantOutput = (
    tuple[Literal[AssistantEventType.CONVERSATION], Conversation]
    | tuple[Literal[AssistantEventType.MESSAGE], AssistantMessageOrStatusUnion]
)

AnyAssistantGeneratedQuery = (
    AssistantTrendsQuery | AssistantFunnelsQuery | AssistantRetentionQuery | AssistantHogQLQuery
)
AnyAssistantSupportedQuery = TrendsQuery | FunnelsQuery | RetentionQuery | HogQLQuery
# We define this since AssistantMessageUnion is a type and wouldn't work with isinstance()
ASSISTANT_MESSAGE_TYPES = (
    HumanMessage,
    NotebookUpdateMessage,
    AssistantMessage,
    VisualizationMessage,
    FailureMessage,
    ReasoningMessage,
    AssistantToolCallMessage,
    PlanningMessage,
    TaskExecutionMessage,
    MultiVisualizationMessage,
)


def replace(_: Any | None, right: Any | None) -> Any | None:
    return right


def append(left: Sequence, right: Sequence) -> Sequence:
    """
    Appends the right value to the state field.
    """
    return [*left, *right]


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


IntermediateStep = tuple[AgentAction, Optional[str]]

StateType = TypeVar("StateType", bound=BaseModel)
PartialStateType = TypeVar("PartialStateType", bound=BaseModel)


class BaseState(BaseModel):
    """Base state class with reset functionality."""

    @classmethod
    def get_reset_state(cls) -> Self:
        """Returns a new instance with all fields reset to their default values."""
        return cls(**{k: v.default for k, v in cls.model_fields.items()})

    start_id: Optional[str] = Field(default=None)
    """
    The ID of the message from which the conversation started.
    """
    graph_status: Optional[Literal["resumed", "interrupted", ""]] = Field(default=None)
    """
    Whether the graph was interrupted or resumed.
    """


class _SharedAssistantState(BaseState):
    """
    The state of the root node.
    """

    intermediate_steps: Optional[list[IntermediateStep]] = Field(default=None)
    """
    Actions taken by the query planner agent.
    """
    plan: Optional[str] = Field(default=None)
    """
    The insight generation plan.
    """
    query_planner_previous_response_id: Optional[str] = Field(default=None)
    """
    The ID of the previous OpenAI Responses API response made by the query planner.
    """
    query_planner_intermediate_messages: Optional[Sequence[LangchainBaseMessage]] = Field(default=None)
    """
    The intermediate messages from the query planner agent.
    """

    onboarding_question: Optional[str] = Field(default=None)
    """
    A clarifying question asked during the onboarding process.
    """

    memory_collection_messages: Annotated[Optional[Sequence[LangchainBaseMessage]], replace] = Field(default=None)
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
    search_insights_query: Optional[str] = Field(default=None)
    """
    The user's search query for finding existing insights.
    """
    session_summarization_query: Optional[str] = Field(default=None)
    """
    The user's query for summarizing sessions. Always pass the user's complete, unmodified query.
    """
    should_use_current_filters: Optional[bool] = Field(default=None)
    """
    Whether to use current filters from user's UI to find relevant sessions.
    """
    notebook_short_id: Optional[str] = Field(default=None)
    """
    The short ID of the notebook being used.
    """


class AssistantState(_SharedAssistantState):
    messages: Annotated[Sequence[AssistantMessageUnion], add_and_merge_messages] = Field(default=[])
    """
    Messages exposed to the user.
    """


class PartialAssistantState(_SharedAssistantState):
    messages: Sequence[AssistantMessageUnion] = Field(default=[])
    """
    Messages exposed to the user.
    """


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
    TRENDS_GENERATOR = "trends_generator"
    TRENDS_GENERATOR_TOOLS = "trends_generator_tools"
    FUNNEL_GENERATOR = "funnel_generator"
    FUNNEL_GENERATOR_TOOLS = "funnel_generator_tools"
    RETENTION_GENERATOR = "retention_generator"
    RETENTION_GENERATOR_TOOLS = "retention_generator_tools"
    QUERY_PLANNER = "query_planner"
    QUERY_PLANNER_TOOLS = "query_planner_tools"
    SQL_GENERATOR = "sql_generator"
    SQL_GENERATOR_TOOLS = "sql_generator_tools"
    QUERY_EXECUTOR = "query_executor"
    MEMORY_COLLECTOR = "memory_collector"
    MEMORY_COLLECTOR_TOOLS = "memory_collector_tools"
    INKEEP_DOCS = "inkeep_docs"
    INSIGHT_RAG_CONTEXT = "insight_rag_context"
    INSIGHTS_SUBGRAPH = "insights_subgraph"
    TITLE_GENERATOR = "title_generator"
    INSIGHTS_SEARCH = "insights_search"
    SESSION_SUMMARIZATION = "session_summarization"


class AssistantMode(StrEnum):
    ASSISTANT = "assistant"
    INSIGHTS_TOOL = "insights_tool"
    DEEP_RESEARCH = "deep_research"


class WithCommentary(BaseModel):
    """
    Use this class as a mixin to your tool calls, so that the `Assistant` class can parse the commentary from the tool call chunks stream.
    """

    commentary: str = Field(
        description="A commentary on what you are doing, using the first person: 'I am doing this because...'"
    )


class InsightArtifact(BaseModel):
    """
    An artifacts created by a task.
    """

    id: str
    query: Union[AssistantTrendsQuery, AssistantFunnelsQuery, AssistantRetentionQuery, AssistantHogQLQuery]
    description: str
