import uuid
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Generic, Literal, Optional, Self, TypeVar, Union

from langchain_core.agents import AgentAction
from langchain_core.messages import (
    AIMessageChunk,
    BaseMessage as LangchainBaseMessage,
)
from langgraph.graph import END, START
from pydantic import BaseModel, ConfigDict, Field

from posthog.schema import (
    AssistantEventType,
    AssistantFunnelsQuery,
    AssistantGenerationStatusEvent,
    AssistantHogQLQuery,
    AssistantMessage,
    AssistantRetentionQuery,
    AssistantToolCallMessage,
    AssistantTrendsQuery,
    AssistantUpdateEvent,
    ContextMessage,
    FailureMessage,
    FunnelsQuery,
    HogQLQuery,
    HumanMessage,
    MultiVisualizationMessage,
    NotebookUpdateMessage,
    PlanningMessage,
    ReasoningMessage,
    RetentionQuery,
    RevenueAnalyticsGrossRevenueQuery,
    RevenueAnalyticsMetricsQuery,
    RevenueAnalyticsMRRQuery,
    RevenueAnalyticsTopCustomersQuery,
    TaskExecutionItem,
    TaskExecutionMessage,
    TaskExecutionStatus,
    TrendsQuery,
    VisualizationMessage,
)

from ee.models import Conversation

AIMessageUnion = Union[
    AssistantMessage,
    VisualizationMessage,
    FailureMessage,
    AssistantToolCallMessage,
    MultiVisualizationMessage,
    ReasoningMessage,
    PlanningMessage,
    TaskExecutionMessage,
]
AssistantMessageUnion = Union[HumanMessage, AIMessageUnion, NotebookUpdateMessage, ContextMessage]
AssistantResultUnion = Union[AssistantMessageUnion, AssistantUpdateEvent, AssistantGenerationStatusEvent]

AssistantOutput = (
    tuple[Literal[AssistantEventType.CONVERSATION], Conversation]
    | tuple[Literal[AssistantEventType.MESSAGE], AssistantMessageUnion]
    | tuple[Literal[AssistantEventType.STATUS], AssistantGenerationStatusEvent]
    | tuple[Literal[AssistantEventType.UPDATE], AssistantUpdateEvent]
)

AnyAssistantGeneratedQuery = (
    AssistantTrendsQuery | AssistantFunnelsQuery | AssistantRetentionQuery | AssistantHogQLQuery
)
AnyAssistantSupportedQuery = (
    TrendsQuery
    | FunnelsQuery
    | RetentionQuery
    | HogQLQuery
    | RevenueAnalyticsGrossRevenueQuery
    | RevenueAnalyticsMetricsQuery
    | RevenueAnalyticsMRRQuery
    | RevenueAnalyticsTopCustomersQuery
)
# We define this since AssistantMessageUnion is a type and wouldn't work with isinstance()
ASSISTANT_MESSAGE_TYPES = (
    HumanMessage,
    NotebookUpdateMessage,
    AssistantMessage,
    VisualizationMessage,
    FailureMessage,
    AssistantToolCallMessage,
    MultiVisualizationMessage,
    ContextMessage,
    ReasoningMessage,
    PlanningMessage,
    TaskExecutionMessage,
)


def replace(_: Any | None, right: Any | None) -> Any | None:
    return right


def append(left: Sequence, right: Sequence) -> Sequence:
    """
    Appends the right value to the state field.
    """
    return [*left, *right]


T = TypeVar("T")


class ReplaceMessages(Generic[T], list[T]):
    """
    Replaces the existing messages with the new messages.
    """


def add_and_merge_messages(
    left_value: Sequence[AssistantMessageUnion], right_value: Sequence[AssistantMessageUnion]
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
    left = list(left_value)
    right = list(right_value)

    # assign missing ids
    for m in left:
        if m.id is None:
            m.id = str(uuid.uuid4())
    for m in right:
        if m.id is None:
            m.id = str(uuid.uuid4())

    if isinstance(right_value, ReplaceMessages):
        return right

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


class TaskArtifact(BaseModel):
    """
    Base artifact created by a task.
    """

    id: str | int | None = None  # The id of the object referenced by the artifact
    task_id: str  # The id of the task that created the artifact
    content: str  # A string content attached to the artifact


class InsightArtifact(TaskArtifact):
    """
    An insight artifact created by a task.
    """

    query: Union[AssistantTrendsQuery, AssistantFunnelsQuery, AssistantRetentionQuery, AssistantHogQLQuery]


class TaskResult(BaseModel):
    """
    The result of an individual task.
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    result: str
    artifacts: Sequence[TaskArtifact] = Field(default=[])
    status: TaskExecutionStatus


class InsightQuery(BaseModel):
    """
    A single insight query to be included in a dashboard.
    Includes the name and description of the insight to be included in the dashboard.
    """

    name: str = Field(
        description="The short name of the insight to be included in the dashboard, it will be used in the dashboard tile. So keep it short and concise. It will be displayed as a header in the insight tile, so make sure it is starting with a capital letter. Be specific about time periods and filters if the user mentioned them. Do not be general or vague."
    )
    description: str = Field(
        description="The detailed description of the insight to be included in the dashboard. Include all relevant context about the insight from earlier messages too, as the tool won't see that conversation history. Do not forget fiters, properties, event names if the user mentioned them. Be specific about time periods and filters if the user mentioned them. Do not be general or vague."
    )


class BaseState(BaseModel):
    """Base state class with reset functionality."""

    @classmethod
    def get_reset_state(cls) -> Self:
        """Returns a new instance with all fields reset to their default values."""
        return cls(**{k: v.default for k, v in cls.model_fields.items()})


class BaseStateWithMessages(BaseState):
    start_id: Optional[str] = Field(default=None)
    """
    The ID of the message from which the conversation started.
    """
    start_dt: Optional[datetime] = Field(default=None)
    """
    The datetime of the start of the conversation. Use this datetime to keep the cache.
    """
    graph_status: Optional[Literal["resumed", "interrupted", ""]] = Field(default=None)
    """
    Whether the graph was interrupted or resumed.
    """
    messages: Sequence[AssistantMessageUnion] = Field(default=[])
    """
    Messages exposed to the user.
    """


class BaseStateWithTasks(BaseState):
    tasks: Annotated[Optional[list[TaskExecutionItem]], replace] = Field(default=None)
    """
    Deprecated.
    """
    task_results: Annotated[list[TaskResult], append] = Field(default=[])  # pyright: ignore[reportUndefinedVariable]
    """
    Results of tasks executed by assistants.
    """


class BaseStateWithIntermediateSteps(BaseState):
    intermediate_steps: Optional[list[IntermediateStep]] = Field(default=None)
    """
    Actions taken by the query planner agent.
    """


class _SharedAssistantState(BaseStateWithMessages, BaseStateWithIntermediateSteps):
    """
    The state of the root node.
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
    root_tool_call_id: Annotated[Optional[str], replace] = Field(default=None)
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
    root_tool_calls_count: Annotated[Optional[int], replace] = Field(default=None)
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
    summary_title: Optional[str] = Field(default=None)
    """
    The name of the summary to generate, based on the user's query and/or current filters.
    """
    notebook_short_id: Optional[str] = Field(default=None)
    """
    The short ID of the notebook being used.
    """
    dashboard_name: Optional[str] = Field(default=None)
    """
    The name of the dashboard to be created based on the user request.
    """
    selected_insight_ids: Optional[list[int]] = Field(default=None)
    """
    The selected insights to be included in the dashboard.
    """
    search_insights_queries: Optional[list[InsightQuery]] = Field(default=None)
    """
    The user's queries to search for insights.
    """
    dashboard_id: Optional[int] = Field(default=None)
    """
    The ID of the dashboard to be edited.
    """


class AssistantState(_SharedAssistantState):
    messages: Annotated[Sequence[AssistantMessageUnion], add_and_merge_messages] = Field(default=[])
    """
    Messages exposed to the user.
    """


class PartialAssistantState(_SharedAssistantState):
    pass


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
    TITLE_GENERATOR = "title_generator"
    INSIGHTS_SEARCH = "insights_search"
    SESSION_SUMMARIZATION = "session_summarization"
    DASHBOARD_CREATION = "dashboard_creation"
    DASHBOARD_CREATION_EXECUTOR = "dashboard_creation_executor"
    HOGQL_GENERATOR = "hogql_generator"
    HOGQL_GENERATOR_TOOLS = "hogql_generator_tools"
    SESSION_REPLAY_FILTER = "session_replay_filter"
    SESSION_REPLAY_FILTER_OPTIONS_TOOLS = "session_replay_filter_options_tools"
    REVENUE_ANALYTICS_FILTER = "revenue_analytics_filter"
    REVENUE_ANALYTICS_FILTER_OPTIONS_TOOLS = "revenue_analytics_filter_options_tools"


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


class MessageAction(BaseModel):
    type: Literal["MESSAGE"] = "MESSAGE"
    message: AssistantMessageUnion


class MessageChunkAction(BaseModel):
    type: Literal["MESSAGE_CHUNK"] = "MESSAGE_CHUNK"
    message: AIMessageChunk


class NodeStartAction(BaseModel):
    type: Literal["NODE_START"] = "NODE_START"


class NodeEndAction(Generic[PartialStateType], BaseModel):
    type: Literal["NODE_END"] = "NODE_END"
    state: PartialStateType


AssistantActionUnion = MessageAction | MessageChunkAction | NodeStartAction | NodeEndAction


class NodePath(BaseModel):
    name: str
    tool_call_id: str | None = None


class AssistantDispatcherEvent(BaseModel):
    action: AssistantActionUnion = Field(discriminator="type")
    node_path: tuple[NodePath, ...]


class LangGraphUpdateEvent(BaseModel):
    update: Any
    node_name: str


class TodoItem(BaseModel):
    content: str = Field(..., min_length=1)
    status: Literal["pending", "in_progress", "completed"]
    id: str
    priority: Literal["low", "medium", "high"]
