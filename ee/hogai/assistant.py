from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
import traceback  # TODO(DEEP_RESEARCH): Remove this
from typing import Any, Literal, Optional, cast
from uuid import UUID, uuid4

import posthoganalytics
import structlog
from asgiref.sync import async_to_sync
from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.messages import AIMessageChunk
from langchain_core.runnables.config import RunnableConfig
from langgraph.errors import GraphRecursionError
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StreamMode
from posthoganalytics.ai.langchain.callbacks import CallbackHandler
from pydantic import BaseModel

from ee.hogai.graph import (
    AssistantGraph,
    FunnelGeneratorNode,
    InsightsAssistantGraph,
    MemoryInitializerNode,
    QueryExecutorNode,
    RetentionGeneratorNode,
    SchemaGeneratorNode,
    SQLGeneratorNode,
    TrendsGeneratorNode,
)
from ee.hogai.graph.base import AssistantNode
from ee.hogai.graph.deep_research.base.nodes import DeepResearchNode
from ee.hogai.graph.taxonomy.types import TaxonomyNodeName
from ee.hogai.graph.deep_research.graph import DeepResearchAssistantGraph
from ee.hogai.tool import CONTEXTUAL_TOOL_NAME_TO_TOOL
from ee.hogai.utils.exceptions import GenerationCanceled
from ee.hogai.utils.helpers import (
    extract_content_from_ai_message,
    find_last_ui_context,
    should_output_assistant_message,
)
from ee.hogai.utils.state import (
    GraphMessageUpdateTuple,
    GraphTaskStartedUpdateTuple,
    GraphValueUpdateTuple,
    is_message_update,
    is_state_update,
    is_task_started_update,
    is_value_update,
    merge_message_chunk,
    validate_state_update,
    validate_value_update,
)
from ee.hogai.utils.types import (
    ASSISTANT_MESSAGE_TYPES,
    AssistantMessageOrStatusUnion,
    AssistantMessageUnion,
    AssistantMode,
    AssistantNodeName,
    AssistantOutput,
    AssistantState,
    PartialAssistantState,
)
from ee.hogai.graph.deep_research.types import (
    DeepResearchNodeName,
    DeepResearchState,
    PartialDeepResearchState,
)
from ee.hogai.utils.types.composed import MaxGraphState, MaxNodeName
from ee.models import Conversation
from posthog.event_usage import report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.models import Action, Team, User
from posthog.schema import (
    AssistantEventType,
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
    AssistantMessage,
    AssistantMessageType,
    FailureMessage,
    HumanMessage,
    MaxBillingContext,
    ReasoningMessage,
    VisualizationMessage,
)
from posthog.sync import database_sync_to_async

VISUALIZATION_NODES: dict[MaxNodeName, type[SchemaGeneratorNode]] = {
    AssistantNodeName.TRENDS_GENERATOR: TrendsGeneratorNode,
    AssistantNodeName.FUNNEL_GENERATOR: FunnelGeneratorNode,
    AssistantNodeName.RETENTION_GENERATOR: RetentionGeneratorNode,
    AssistantNodeName.SQL_GENERATOR: SQLGeneratorNode,
}

VISUALIZATION_NODES_TOOL_CALL_MODE: dict[MaxNodeName, type[AssistantNode | DeepResearchNode]] = {
    **VISUALIZATION_NODES,
    AssistantNodeName.QUERY_EXECUTOR: QueryExecutorNode,
}

STREAMING_NODES: set[MaxNodeName] = {
    AssistantNodeName.ROOT,
    AssistantNodeName.INKEEP_DOCS,
    AssistantNodeName.MEMORY_ONBOARDING,
    AssistantNodeName.MEMORY_INITIALIZER,
    AssistantNodeName.MEMORY_ONBOARDING_ENQUIRY,
    AssistantNodeName.MEMORY_ONBOARDING_FINALIZE,
    TaxonomyNodeName.LOOP_NODE,
    AssistantNodeName.SESSION_SUMMARIZATION,
    DeepResearchNodeName.ONBOARDING,
    DeepResearchNodeName.PLANNER,
    DeepResearchNodeName.TASK_EXECUTOR,
}
"""Nodes that can stream messages to the client directly from a streaming API (e.g. MaxChatOpenAI)."""


VERBOSE_NODES: set[MaxNodeName] = STREAMING_NODES | {
    AssistantNodeName.MEMORY_INITIALIZER_INTERRUPT,
    AssistantNodeName.ROOT_TOOLS,
    TaxonomyNodeName.TOOLS_NODE,
    DeepResearchNodeName.PLANNER_TOOLS,
    DeepResearchNodeName.TASK_EXECUTOR,
}
"""Nodes that can send messages to the client."""

THINKING_NODES: set[MaxNodeName] = {
    AssistantNodeName.QUERY_PLANNER,
    TaxonomyNodeName.LOOP_NODE,
    AssistantNodeName.SESSION_SUMMARIZATION,
    DeepResearchNodeName.ONBOARDING,
    DeepResearchNodeName.NOTEBOOK_PLANNING,
    DeepResearchNodeName.PLANNER,
    DeepResearchNodeName.REPORT,
}
"""Nodes that pass on thinking messages to the client. Current implementation assumes o3/o4 style of reasoning summaries!"""


logger = structlog.get_logger(__name__)


class Assistant:
    _team: Team
    _state_class: type[MaxGraphState]
    _graph: CompiledStateGraph
    _user: User
    _contextual_tools: dict[str, Any]
    _conversation: Conversation
    _session_id: Optional[str]
    _latest_message: Optional[HumanMessage]
    _state: Optional[MaxGraphState]
    _callback_handler: Optional[BaseCallbackHandler]
    _trace_id: Optional[str | UUID]
    _custom_update_ids: set[str]
    _reasoning_headline_chunk: Optional[str]
    """Like a message chunk, but specifically for the reasoning headline (and just a plain string)."""
    _last_reasoning_headline: Optional[str]
    """Last emitted reasoning headline, to be able to carry it over."""
    _billing_context: Optional[MaxBillingContext]
    _commentary_chunk: Optional[str]
    """Buffer for accumulating partial commentary from tool call chunks."""

    def __init__(
        self,
        team: Team,
        conversation: Conversation,
        *,
        new_message: Optional[HumanMessage] = None,
        mode: AssistantMode = AssistantMode.ASSISTANT,
        user: User,
        session_id: Optional[str] = None,
        contextual_tools: Optional[dict[str, Any]] = None,
        is_new_conversation: bool = False,
        trace_id: Optional[str | UUID] = None,
        tool_call_partial_state: Optional[AssistantState] = None,
        billing_context: Optional[MaxBillingContext] = None,
    ):
        self._team = team
        self._contextual_tools = contextual_tools or {}
        self._user = user
        self._session_id = session_id
        self._conversation = conversation
        self._latest_message = new_message.model_copy(deep=True, update={"id": str(uuid4())}) if new_message else None
        self._is_new_conversation = is_new_conversation
        self._mode = mode
        match mode:
            case AssistantMode.ASSISTANT:
                self._graph = AssistantGraph(team, user).compile_full_graph()
                self._state_class = AssistantState
            case AssistantMode.DEEP_RESEARCH:
                self._graph = DeepResearchAssistantGraph(team, user).compile_full_graph()
                self._state_class = DeepResearchState
            case AssistantMode.INSIGHTS_TOOL:
                self._graph = InsightsAssistantGraph(team, user).compile_full_graph()
                self._state_class = AssistantState
        self._chunks = AIMessageChunk(content="")
        self._tool_call_partial_state = tool_call_partial_state
        self._state = None
        self._callback_handler = (
            CallbackHandler(
                posthoganalytics.default_client,
                distinct_id=user.distinct_id if user else None,
                properties={
                    "conversation_id": str(self._conversation.id),
                    "is_first_conversation": is_new_conversation,
                    "$session_id": self._session_id,
                    "assistant_mode": mode.value,
                },
                trace_id=trace_id,
            )
            if posthoganalytics.default_client
            else None
        )
        self._trace_id = trace_id
        self._custom_update_ids = set()
        self._reasoning_headline_chunk = None
        self._last_reasoning_headline = None
        self._billing_context = billing_context
        self._commentary_chunk = None

    async def ainvoke(self) -> list[tuple[Literal[AssistantEventType.MESSAGE], AssistantMessageUnion]]:
        """Returns all messages in once without streaming."""
        messages = []

        async for event_type, message in self.astream(stream_messages=False):
            if event_type == AssistantEventType.MESSAGE and message.type != AssistantMessageType.AI_REASONING:
                messages.append((event_type, cast(AssistantMessageUnion, message)))

        return messages

    @async_to_sync
    async def invoke(self) -> list[tuple[Literal[AssistantEventType.MESSAGE], AssistantMessageUnion]]:
        """Sync method. Returns all messages in once without streaming."""
        return await self.ainvoke()

    async def astream(self, stream_messages: bool = True) -> AsyncGenerator[AssistantOutput, None]:
        state = await self._init_or_update_state()
        config = self._get_config()

        # Some execution modes don't need to stream messages.
        stream_mode: list[StreamMode] = ["values", "updates", "debug", "custom"]
        if stream_messages:
            stream_mode.append("messages")

        generator: AsyncIterator[Any] = self._graph.astream(
            state, config=config, stream_mode=stream_mode, subgraphs=True
        )

        async with self._lock_conversation():
            # Assign the conversation id to the client.
            if self._is_new_conversation:
                yield AssistantEventType.CONVERSATION, self._conversation

            if self._latest_message and self._mode in [AssistantMode.ASSISTANT, AssistantMode.DEEP_RESEARCH]:
                # Send the last message with the initialized id.
                yield AssistantEventType.MESSAGE, self._latest_message

            last_ai_message: AssistantMessage | None = None
            last_viz_message: VisualizationMessage | None = None
            try:
                async for update in generator:
                    if messages := await self._process_update(update):
                        for message in messages:
                            if isinstance(message, VisualizationMessage):
                                last_viz_message = message
                            if isinstance(message, AssistantMessage):
                                last_ai_message = message
                            if hasattr(message, "id"):
                                if update[1] == "custom":
                                    # Custom updates come from tool calls, we want to deduplicate the messages sent to the client.
                                    self._custom_update_ids.add(message.id)
                                elif message.id in self._custom_update_ids:
                                    continue
                            yield AssistantEventType.MESSAGE, cast(AssistantMessageOrStatusUnion, message)

                # Check if the assistant has requested help.
                state = await self._graph.aget_state(config)
                if state.next:
                    interrupt_messages = []
                    for task in state.tasks:
                        for interrupt in task.interrupts:
                            interrupt_message = (
                                AssistantMessage(content=interrupt.value, id=str(uuid4()))
                                if isinstance(interrupt.value, str)
                                else interrupt.value
                            )
                            interrupt_messages.append(interrupt_message)
                            yield AssistantEventType.MESSAGE, interrupt_message

                    await self._graph.aupdate_state(
                        config,
                        PartialAssistantState(
                            messages=interrupt_messages,
                            # LangGraph by some reason doesn't store the interrupt exceptions in checkpoints.
                            graph_status="interrupted",
                        ),
                    )
            except GraphRecursionError:
                yield (
                    AssistantEventType.MESSAGE,
                    FailureMessage(
                        content="The assistant has reached the maximum number of steps. You can explicitly ask to continue.",
                        id=str(uuid4()),
                    ),
                )
            except Exception as e:
                # Reset the state, so that the next generation starts from the beginning.
                await self._graph.aupdate_state(config, PartialAssistantState.get_reset_state())

                if not isinstance(e, GenerationCanceled):
                    logger.exception("Error in assistant stream", error=e)
                    posthoganalytics.capture_exception(
                        e,
                        distinct_id=self._user.distinct_id if self._user else None,
                        properties={
                            "$session_id": self._session_id,
                            "$ai_trace_id": self._trace_id,
                            "thread_id": self._conversation.id,
                            "tag": "max_ai",
                        },
                    )

                    # This is an unhandled error, so we just stop further generation at this point
                    snapshot = await self._graph.aget_state(config)
                    state_snapshot = validate_state_update(snapshot.values, self._state_class)
                    # Some nodes might have already sent a failure message, so we don't want to send another one.
                    if not state_snapshot.messages or not isinstance(state_snapshot.messages[-1], FailureMessage):
                        # TODO(DEEP_RESEARCH): Remove the version with traceback, it's just for debugging
                        # yield AssistantEventType.MESSAGE, FailureMessage()
                        yield AssistantEventType.MESSAGE, FailureMessage(content=str(traceback.format_exc()))
            finally:
                await self._report_conversation_state(
                    last_assistant_message=last_ai_message, last_visualization_message=last_viz_message
                )

    def _get_config(self) -> RunnableConfig:
        callbacks = [self._callback_handler] if self._callback_handler else None
        config: RunnableConfig = {
            "recursion_limit": 48,
            "callbacks": callbacks,
            "configurable": {
                "thread_id": self._conversation.id,
                "trace_id": self._trace_id,
                "session_id": self._session_id,
                "distinct_id": self._user.distinct_id if self._user else None,
                "contextual_tools": self._contextual_tools,
                "team": self._team,
                "user": self._user,
                "billing_context": self._billing_context,
                # Metadata to be sent to PostHog SDK (error tracking, etc).
                "sdk_metadata": {
                    "assistant_mode": self._mode.value,
                    "tag": "max_ai",
                },
            },
        }
        return config

    async def _init_or_update_state(self):
        config = self._get_config()
        snapshot = await self._graph.aget_state(config)

        # If the graph previously hasn't reset the state, it is an interrupt. We resume from the point of interruption.
        if snapshot.next and self._latest_message:
            saved_state = validate_state_update(snapshot.values, self._state_class)
            if saved_state.graph_status == "interrupted":
                self._state = saved_state
                await self._graph.aupdate_state(
                    config,
                    PartialAssistantState(
                        messages=[self._latest_message], graph_status="resumed", query_generation_retry_count=0
                    ),
                )
                # Return None to indicate that we want to continue the execution from the interrupted point.
                return None

        # Append the new message and reset some fields to their default values.
        initial_state: AssistantState | DeepResearchState
        if self._latest_message and self._mode in [AssistantMode.ASSISTANT, AssistantMode.DEEP_RESEARCH]:
            if self._mode == AssistantMode.DEEP_RESEARCH:
                initial_state = DeepResearchState(
                    messages=[self._latest_message],
                    start_id=self._latest_message.id,
                    graph_status=None,
                    notebook_short_id=None,
                )
            else:
                initial_state = AssistantState(
                    messages=[self._latest_message],
                    start_id=self._latest_message.id,
                    query_generation_retry_count=0,
                    graph_status=None,
                    rag_context=None,
                )
        else:
            initial_state = AssistantState(messages=[])

        if self._tool_call_partial_state:
            for key, value in self._tool_call_partial_state.model_dump().items():
                setattr(initial_state, key, value)
        self._state = initial_state
        return initial_state

    async def _node_to_reasoning_message(
        self, node_name: MaxNodeName, input: AssistantState | DeepResearchState
    ) -> Optional[ReasoningMessage]:
        match node_name:
            case AssistantNodeName.QUERY_PLANNER | TaxonomyNodeName.LOOP_NODE:
                substeps: list[str] = []
                input = cast(AssistantState, input)
                if input:
                    if intermediate_steps := input.intermediate_steps:
                        for action, _ in intermediate_steps:
                            assert isinstance(action.tool_input, dict)
                            match action.tool:
                                case "retrieve_event_properties":
                                    substeps.append(f"Exploring `{action.tool_input['event_name']}` event's properties")
                                case "retrieve_entity_properties":
                                    substeps.append(f"Exploring {action.tool_input['entity']} properties")
                                case "retrieve_event_property_values":
                                    substeps.append(
                                        f"Analyzing `{action.tool_input['event_name']}` event's property `{action.tool_input['property_name']}`"
                                    )
                                case "retrieve_entity_property_values":
                                    substeps.append(
                                        f"Analyzing {action.tool_input['entity']} property `{action.tool_input['property_name']}`"
                                    )
                                case "retrieve_action_properties" | "retrieve_action_property_values":
                                    try:
                                        action_model = await Action.objects.aget(
                                            pk=action.tool_input["action_id"], team__project_id=self._team.project_id
                                        )
                                        if action.tool == "retrieve_action_properties":
                                            substeps.append(f"Exploring `{action_model.name}` action properties")
                                        elif action.tool == "retrieve_action_property_values":
                                            substeps.append(
                                                f"Analyzing `{action.tool_input['property_name']}` action property of `{action_model.name}`"
                                            )
                                    except Action.DoesNotExist:
                                        pass

                # We don't want to reset back to just "Picking relevant events" after running QueryPlannerTools,
                # so we reuse the last reasoning headline when going back to QueryPlanner
                return ReasoningMessage(
                    content=self._last_reasoning_headline or "Picking relevant events and properties", substeps=substeps
                )
            case AssistantNodeName.TRENDS_GENERATOR:
                return ReasoningMessage(content="Creating trends query")
            case AssistantNodeName.FUNNEL_GENERATOR:
                return ReasoningMessage(content="Creating funnel query")
            case AssistantNodeName.RETENTION_GENERATOR:
                return ReasoningMessage(content="Creating retention query")
            case AssistantNodeName.SQL_GENERATOR:
                return ReasoningMessage(content="Creating SQL query")
            case AssistantNodeName.ROOT_TOOLS:
                assert isinstance(input.messages[-1], AssistantMessage)
                tool_calls = input.messages[-1].tool_calls or []
                assert len(tool_calls) <= 1
                if len(tool_calls) == 0:
                    return None
                tool_call = tool_calls[0]
                if tool_call.name == "create_and_query_insight":
                    return ReasoningMessage(content="Coming up with an insight")
                if tool_call.name == "search_documentation":
                    return ReasoningMessage(content="Checking PostHog docs")
                if tool_call.name == "retrieve_billing_information":
                    return ReasoningMessage(content="Checking your billing data")
                # This tool should be in CONTEXTUAL_TOOL_NAME_TO_TOOL, but it might not be in the rare case
                # when the tool has been removed from the backend since the user's frontent was loaded
                ToolClass = CONTEXTUAL_TOOL_NAME_TO_TOOL.get(tool_call.name)  # type: ignore
                return ReasoningMessage(
                    content=ToolClass(team=self._team, user=self._user).thinking_message
                    if ToolClass
                    else f"Running tool {tool_call.name}"
                )
            case AssistantNodeName.ROOT:
                ui_context = find_last_ui_context(input.messages)
                if ui_context and (ui_context.dashboards or ui_context.insights):
                    return ReasoningMessage(content="Calculating context")
                return None
            case AssistantNodeName.SESSION_SUMMARIZATION:
                return ReasoningMessage(content="Summarizing session recordings")
            case DeepResearchNodeName.PLANNER_TOOLS:
                assert isinstance(input.messages[-1], AssistantMessage)
                tool_calls = input.messages[-1].tool_calls or []
                assert len(tool_calls) <= 1
                if len(tool_calls) == 0:
                    return None
                tool_call = tool_calls[0]
                if tool_call.name == "todo_write":
                    return ReasoningMessage(content="Writing todos")
                elif tool_call.name == "todo_read":
                    return ReasoningMessage(content="Reading todos")
                elif tool_call.name == "artifacts_read":
                    return ReasoningMessage(content="Reading artifacts")
                elif tool_call.name == "execute_tasks":
                    return ReasoningMessage(content="Executing tasks")
                elif tool_call.name == "result_write":
                    return ReasoningMessage(content="Writing intermediate results")
                elif tool_call.name == "finalize_research":
                    return ReasoningMessage(content="Finalizing research")
                return None
            case _:
                return None

    async def _process_update(self, update: Any) -> list[BaseModel] | None:
        if update[1] == "custom":
            # Custom streams come from a tool call
            # If it's a LangGraph-based chunk, we remove the first two elements, which are "custom" and the parent graph namespace
            update = update[2]

        update = update[1:]  # we remove the first element, which is the node/subgraph node name
        if is_state_update(update):
            _, new_state = update
            self._state = validate_state_update(new_state, self._state_class)
        elif is_value_update(update) and (new_messages := self._process_value_update(update)):
            return new_messages
        elif is_message_update(update) and (new_message := self._process_message_update(update)):
            return [new_message]
        elif is_task_started_update(update) and (new_message := await self._process_task_started_update(update)):
            return [new_message]
        return None

    def _process_value_update(self, update: GraphValueUpdateTuple) -> list[BaseModel] | None:
        _, maybe_state_update = update
        state_update = validate_value_update(maybe_state_update)
        # this needs full type annotation otherwise mypy complains
        visualization_nodes: (
            dict[MaxNodeName, type[AssistantNode | DeepResearchNode]] | dict[MaxNodeName, type[SchemaGeneratorNode]]
        ) = VISUALIZATION_NODES_TOOL_CALL_MODE if self._mode == AssistantMode.INSIGHTS_TOOL else VISUALIZATION_NODES
        if intersected_nodes := state_update.keys() & visualization_nodes.keys():
            # Reset chunks when schema validation fails.
            self._chunks = AIMessageChunk(content="")

            node_name: MaxNodeName = intersected_nodes.pop()
            node_val = state_update[node_name]
            if not isinstance(node_val, PartialAssistantState | PartialDeepResearchState):
                return None
            if node_val.messages:
                return list(node_val.messages)
            elif isinstance(node_val, PartialAssistantState) and node_val.intermediate_steps:
                return [AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.GENERATION_ERROR)]

        for node_name in VERBOSE_NODES:
            if node_val := state_update.get(node_name):
                if isinstance(node_val, PartialAssistantState | PartialDeepResearchState) and node_val.messages:
                    self._chunks = AIMessageChunk(content="")
                    _messages: list[BaseModel] = []
                    for candidate_message in node_val.messages:
                        if should_output_assistant_message(candidate_message):
                            _messages.append(candidate_message)
                    return _messages

        for node_name in THINKING_NODES:
            if node_val := state_update.get(node_name):
                # If update involves new state from a thinking node, we reset the thinking headline to be sure
                self._reasoning_headline_chunk = None

        return [AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.ACK)]

    def _process_message_update(self, update: GraphMessageUpdateTuple) -> BaseModel | None:
        langchain_message, langgraph_state = update[1]

        if isinstance(langchain_message, ASSISTANT_MESSAGE_TYPES):
            # Immediately return assistant messages coming from custom message streams
            return langchain_message

        if not isinstance(langchain_message, AIMessageChunk):
            return None

        node_name: MaxNodeName = langgraph_state["langgraph_node"]

        # Check for commentary in tool call chunks first
        if commentary := self._extract_commentary_from_tool_call_chunk(langchain_message):
            return AssistantMessage(content=commentary)

        # Check for reasoning content (for all nodes that support it)
        if reasoning := langchain_message.additional_kwargs.get("reasoning"):
            if reasoning_headline := self._chunk_reasoning_headline(reasoning):
                return ReasoningMessage(content=reasoning_headline)

        # Only process streaming nodes
        if node_name not in STREAMING_NODES:
            return None

        # Merge message chunks
        self._chunks = merge_message_chunk(self._chunks, langchain_message)

        if node_name == AssistantNodeName.MEMORY_INITIALIZER:
            return self._process_memory_initializer_chunk(langchain_message)

        # Extract and process content
        message_content = extract_content_from_ai_message(self._chunks)
        if not message_content:
            return None

        return AssistantMessage(content=message_content)

    def _process_memory_initializer_chunk(self, langchain_message: AIMessageChunk) -> Optional[AssistantMessage]:
        """Process memory initializer specific chunk logic."""
        if not MemoryInitializerNode.should_process_message_chunk(langchain_message):
            return None
        return AssistantMessage(content=MemoryInitializerNode.format_message(cast(str, self._chunks.content)))

    def _chunk_reasoning_headline(self, reasoning: dict[str, Any]) -> Optional[str]:
        """Process a chunk of OpenAI `reasoning`, and if a new headline was just finalized, return it."""
        try:
            if summary := reasoning.get("summary"):
                summary_text_chunk = summary[0]["text"]
            else:
                self._reasoning_headline_chunk = None  # Reset as we don't have any summary yet
                return None
        except Exception as e:
            logger.exception("Error in chunk_reasoning_headline", error=e)
            capture_exception(e)  # not expected, so let's capture
            self._reasoning_headline_chunk = None
            return None

        bold_marker_index = summary_text_chunk.find("**")
        if bold_marker_index == -1:
            # No bold markers - continue building headline if in progress
            if self._reasoning_headline_chunk is not None:
                self._reasoning_headline_chunk += summary_text_chunk
            return None

        # Handle bold markers
        if self._reasoning_headline_chunk is None:
            # Start of headline
            remaining_text = summary_text_chunk[bold_marker_index + 2 :]
            end_index = remaining_text.find("**")

            if end_index != -1:
                # Complete headline in one chunk
                self._last_reasoning_headline = remaining_text[:end_index]
                return self._last_reasoning_headline
            else:
                # Start of multi-chunk headline
                self._reasoning_headline_chunk = remaining_text
        else:
            # End of headline
            self._reasoning_headline_chunk += summary_text_chunk[:bold_marker_index]
            self._last_reasoning_headline = self._reasoning_headline_chunk
            self._reasoning_headline_chunk = None
            return self._last_reasoning_headline

        return None

    def _extract_commentary_from_tool_call_chunk(self, langchain_message: AIMessageChunk) -> Optional[str]:
        """Extract commentary from tool call chunks.

        Handles partial JSON parsing for "commentary": "some text" patterns
        Returns the commentary content when a complete or partial one is found.
        """
        if not langchain_message.tool_call_chunks:
            return None

        for chunk in langchain_message.tool_call_chunks:
            if not chunk or not chunk.get("args"):
                continue

            args_chunk = chunk["args"]
            if not isinstance(args_chunk, str):
                continue

            # Accumulate chunks
            if self._commentary_chunk is None:
                self._commentary_chunk = args_chunk
            else:
                self._commentary_chunk = self._commentary_chunk + args_chunk

            # Try to extract commentary from accumulated chunks
            current_buffer = self._commentary_chunk

            # Look for "commentary": pattern
            commentary_pattern = '"commentary":'
            if commentary_pattern in current_buffer:
                # Find the start of the commentary value
                start_idx = current_buffer.find(commentary_pattern) + len(commentary_pattern)
                remaining = current_buffer[start_idx:].lstrip()

                if remaining.startswith('"'):
                    # We have the opening quote
                    value_start = 1
                    value_buffer = remaining[value_start:]

                    # Check if we have a closing quote
                    closing_quote_idx = value_buffer.find('"')

                    if closing_quote_idx != -1:
                        # Complete commentary found
                        commentary = value_buffer[:closing_quote_idx]
                        # Reset buffer for next commentary
                        self._commentary_chunk = None
                        return commentary
                    else:
                        # Partial commentary - return what we have so far
                        # But only if there's actual content
                        if value_buffer:
                            return value_buffer

        return None

    async def _process_task_started_update(self, update: GraphTaskStartedUpdateTuple) -> BaseModel | None:
        _, task_update = update
        node_name = task_update["payload"]["name"]  # type: ignore
        node_input = task_update["payload"]["input"]  # type: ignore
        if reasoning_message := await self._node_to_reasoning_message(node_name, node_input):
            return reasoning_message
        return None

    async def _report_conversation_state(
        self,
        last_assistant_message: AssistantMessage | None = None,
        last_visualization_message: VisualizationMessage | None = None,
    ):
        if not self._user:
            return
        visualization_response = (
            last_visualization_message.model_dump_json(exclude_none=True) if last_visualization_message else None
        )
        output = last_assistant_message.content if isinstance(last_assistant_message, AssistantMessage) else None

        event_config = self._get_analytics_event_config(output, visualization_response)
        if event_config:
            await database_sync_to_async(report_user_action)(self._user, event_config["name"], event_config["args"])

    def _get_analytics_event_config(
        self, output: Optional[str], visualization_response: Optional[str]
    ) -> Optional[dict[str, Any]]:
        """Get analytics event configuration based on assistant mode."""
        base_prompt = self._latest_message.content if self._latest_message else None

        match self._mode:
            case AssistantMode.ASSISTANT:
                return {
                    "name": "chat with ai",
                    "args": {
                        "prompt": base_prompt,
                        "output": output,
                        "response": visualization_response,
                    },
                }
            case AssistantMode.DEEP_RESEARCH:
                return {
                    "name": "deep research",
                    "args": {
                        "prompt": base_prompt,
                        "output": output,
                    },
                }
            case AssistantMode.INSIGHTS_TOOL if self._tool_call_partial_state:
                return {
                    "name": "standalone ai tool call",
                    "args": {
                        "prompt": self._tool_call_partial_state.root_tool_insight_plan,
                        "response": visualization_response,
                        "output": output,
                        "tool_name": "create_and_query_insight",
                    },
                }
            case _:
                return None

    @asynccontextmanager
    async def _lock_conversation(self):
        try:
            self._conversation.status = Conversation.Status.IN_PROGRESS
            await self._conversation.asave(update_fields=["status"])
            yield
        finally:
            self._conversation.status = Conversation.Status.IDLE
            await self._conversation.asave(update_fields=["status", "updated_at"])
