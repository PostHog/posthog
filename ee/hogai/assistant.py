from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
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
from ee.hogai.tool import CONTEXTUAL_TOOL_NAME_TO_TOOL
from ee.hogai.utils.exceptions import GenerationCanceled
from ee.hogai.utils.helpers import find_last_ui_context, should_output_assistant_message
from ee.hogai.utils.state import (
    GraphMessageUpdateTuple,
    GraphTaskStartedUpdateTuple,
    GraphValueUpdateTuple,
    is_message_update,
    is_state_update,
    is_task_started_update,
    is_value_update,
    validate_state_update,
    validate_value_update,
)
from ee.hogai.utils.types import (
    AssistantMessageUnion,
    AssistantMode,
    AssistantNodeName,
    AssistantOutput,
    AssistantState,
    PartialAssistantState,
)
from ee.models import Conversation
from posthog.event_usage import report_user_action
from posthog.models import Action, Team, User
from posthog.schema import (
    AssistantEventType,
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
    AssistantMessage,
    AssistantMessageType,
    FailureMessage,
    HumanMessage,
    ReasoningMessage,
    VisualizationMessage,
)
from posthog.sync import database_sync_to_async

VISUALIZATION_NODES: dict[AssistantNodeName, type[SchemaGeneratorNode]] = {
    AssistantNodeName.TRENDS_GENERATOR: TrendsGeneratorNode,
    AssistantNodeName.FUNNEL_GENERATOR: FunnelGeneratorNode,
    AssistantNodeName.RETENTION_GENERATOR: RetentionGeneratorNode,
    AssistantNodeName.SQL_GENERATOR: SQLGeneratorNode,
}

VISUALIZATION_NODES_TOOL_CALL_MODE: dict[AssistantNodeName, type[AssistantNode]] = {
    **VISUALIZATION_NODES,
    AssistantNodeName.QUERY_EXECUTOR: QueryExecutorNode,
}

STREAMING_NODES: set[AssistantNodeName] = {
    AssistantNodeName.ROOT,
    AssistantNodeName.INKEEP_DOCS,
    AssistantNodeName.MEMORY_ONBOARDING,
    AssistantNodeName.MEMORY_INITIALIZER,
    AssistantNodeName.MEMORY_ONBOARDING_ENQUIRY,
    AssistantNodeName.MEMORY_ONBOARDING_FINALIZE,
    AssistantNodeName.FILTER_OPTIONS,
    AssistantNodeName.FILTER_OPTIONS_TOOLS,
}
"""Nodes that can stream messages to the client."""


VERBOSE_NODES = STREAMING_NODES | {
    AssistantNodeName.MEMORY_INITIALIZER_INTERRUPT,
    AssistantNodeName.ROOT_TOOLS,
    AssistantNodeName.FILTER_OPTIONS,
    AssistantNodeName.FILTER_OPTIONS_TOOLS,
}
"""Nodes that can send messages to the client."""

THINKING_NODES = {
    AssistantNodeName.QUERY_PLANNER,
}
"""Nodes that pass on thinking messages to the client. Current implementation assumes o3/o4 style of reasoning summaries!"""


logger = structlog.get_logger(__name__)


class Assistant:
    _team: Team
    _graph: CompiledStateGraph
    _user: User
    _contextual_tools: dict[str, Any]
    _conversation: Conversation
    _latest_message: Optional[HumanMessage]
    _state: Optional[AssistantState]
    _callback_handler: Optional[BaseCallbackHandler]
    _trace_id: Optional[str | UUID]
    _custom_update_ids: set[str]
    _reasoning_headline_chunk: Optional[str]
    """Like a message chunk, but specifically for the reasoning headline (and just a plain string)."""
    _last_reasoning_headline: Optional[str]
    """Last emittted reasoning headline, to be able to carry it over."""

    def __init__(
        self,
        team: Team,
        conversation: Conversation,
        *,
        new_message: Optional[HumanMessage] = None,
        mode: AssistantMode = AssistantMode.ASSISTANT,
        user: User,
        contextual_tools: Optional[dict[str, Any]] = None,
        is_new_conversation: bool = False,
        trace_id: Optional[str | UUID] = None,
        tool_call_partial_state: Optional[AssistantState] = None,
    ):
        self._team = team
        self._contextual_tools = contextual_tools or {}
        self._user = user
        self._conversation = conversation
        self._latest_message = new_message.model_copy(deep=True, update={"id": str(uuid4())}) if new_message else None
        self._is_new_conversation = is_new_conversation
        self._mode = mode
        match mode:
            case AssistantMode.ASSISTANT:
                self._graph = AssistantGraph(team, user).compile_full_graph()
            case AssistantMode.INSIGHTS_TOOL:
                self._graph = InsightsAssistantGraph(team, user).compile_full_graph()
            case _:
                raise ValueError(f"Invalid assistant mode: {mode}")
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

            if self._latest_message and self._mode == AssistantMode.ASSISTANT:
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
                            yield AssistantEventType.MESSAGE, cast(AssistantMessageUnion, message)

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
                    posthoganalytics.capture_exception(e)

                    # This is an unhandled error, so we just stop further generation at this point
                    snapshot = await self._graph.aget_state(config)
                    state_snapshot = validate_state_update(snapshot.values)
                    # Some nodes might have already sent a failure message, so we don't want to send another one.
                    if not state_snapshot.messages or not isinstance(state_snapshot.messages[-1], FailureMessage):
                        yield AssistantEventType.MESSAGE, FailureMessage()
            finally:
                await self._report_conversation_state(
                    last_assistant_message=last_ai_message, last_visualization_message=last_viz_message
                )

    @property
    def _initial_state(self) -> AssistantState:
        if self._latest_message and self._mode == AssistantMode.ASSISTANT:
            return AssistantState(
                messages=[self._latest_message],
                start_id=self._latest_message.id,
            )
        else:
            return AssistantState(
                messages=[],
            )

    def _get_config(self) -> RunnableConfig:
        callbacks = [self._callback_handler] if self._callback_handler else None
        config: RunnableConfig = {
            "recursion_limit": 48,
            "callbacks": callbacks,
            "configurable": {
                "thread_id": self._conversation.id,
                "trace_id": self._trace_id,
                "distinct_id": self._user.distinct_id if self._user else None,
                "contextual_tools": self._contextual_tools,
                "team": self._team,
                "user": self._user,
            },
        }
        return config

    async def _init_or_update_state(self):
        config = self._get_config()
        snapshot = await self._graph.aget_state(config)

        # If the graph previously hasn't reset the state, it is an interrupt. We resume from the point of interruption.
        if snapshot.next and self._latest_message:
            saved_state = validate_state_update(snapshot.values)
            if saved_state.graph_status == "interrupted":
                self._state = saved_state
                await self._graph.aupdate_state(
                    config, PartialAssistantState(messages=[self._latest_message], graph_status="resumed")
                )
                # Return None to indicate that we want to continue the execution from the interrupted point.
                return None

        initial_state = self._initial_state
        if self._tool_call_partial_state:
            for key, value in self._tool_call_partial_state.model_dump().items():
                setattr(initial_state, key, value)
        self._state = initial_state
        return initial_state

    async def _node_to_reasoning_message(
        self, node_name: AssistantNodeName, input: AssistantState
    ) -> Optional[ReasoningMessage]:
        match node_name:
            case AssistantNodeName.QUERY_PLANNER | AssistantNodeName.FILTER_OPTIONS_TOOLS:
                substeps: list[str] = []
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
                # This tool should be in CONTEXTUAL_TOOL_NAME_TO_TOOL, but it might not be in the rare case
                # when the tool has been removed from the backend since the user's frontent was loaded
                ToolClass = CONTEXTUAL_TOOL_NAME_TO_TOOL.get(tool_call.name)  # type: ignore
                return ReasoningMessage(
                    content=ToolClass().thinking_message if ToolClass else f"Running tool {tool_call.name}"
                )
            case AssistantNodeName.ROOT:
                ui_context = find_last_ui_context(input.messages)
                if ui_context and (ui_context.dashboards or ui_context.insights):
                    return ReasoningMessage(content="Calculating context")
                return None
            case _:
                return None

    async def _process_update(self, update: Any) -> list[BaseModel] | None:
        if update[1] == "custom":
            # Custom streams come from a tool call
            update = update[2]
        update = update[1:]  # we remove the first element, which is the node/subgraph node name
        if is_state_update(update):
            _, new_state = update
            self._state = validate_state_update(new_state)
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
            dict[AssistantNodeName, type[AssistantNode]] | dict[AssistantNodeName, type[SchemaGeneratorNode]]
        ) = VISUALIZATION_NODES if self._mode == AssistantMode.ASSISTANT else VISUALIZATION_NODES_TOOL_CALL_MODE
        if intersected_nodes := state_update.keys() & visualization_nodes.keys():
            # Reset chunks when schema validation fails.
            self._chunks = AIMessageChunk(content="")

            node_name = intersected_nodes.pop()
            node_val = state_update[node_name]
            if not isinstance(node_val, PartialAssistantState):
                return None
            if node_val.messages:
                return list(node_val.messages)
            elif node_val.intermediate_steps:
                return [AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.GENERATION_ERROR)]

        for node_name in VERBOSE_NODES:
            if node_val := state_update.get(node_name):
                if isinstance(node_val, PartialAssistantState) and node_val.messages:
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

        return None

    def _process_message_update(self, update: GraphMessageUpdateTuple) -> BaseModel | None:
        langchain_message, langgraph_state = update[1]
        if isinstance(langchain_message, AIMessageChunk):
            node_name = langgraph_state["langgraph_node"]
            if node_name in STREAMING_NODES:
                self._chunks += langchain_message  # type: ignore
                if node_name == AssistantNodeName.MEMORY_INITIALIZER:
                    if not MemoryInitializerNode.should_process_message_chunk(langchain_message):
                        return None
                    else:
                        return AssistantMessage(
                            content=MemoryInitializerNode.format_message(cast(str, self._chunks.content))
                        )
                if self._chunks.content:
                    # Only return an in-progress message if there is already some content (and not e.g. just tool calls)
                    return AssistantMessage(content=cast(str, self._chunks.content))
            if reasoning := langchain_message.additional_kwargs.get("reasoning"):
                if reasoning_headline := self._chunk_reasoning_headline(reasoning):
                    return ReasoningMessage(content=reasoning_headline)
        return None

    def _chunk_reasoning_headline(self, reasoning: dict[str, Any]) -> Optional[str]:
        """Process a chunk of OpenAI `reasoning`, and if a new headline was just finalized, return it."""
        try:
            summary_text_chunk = reasoning["summary"][0]["text"]
        except (KeyError, IndexError):
            self._reasoning_headline_chunk = None  # Not expected, so let's just reset
            return None

        index_of_bold_in_text = summary_text_chunk.find("**")
        if index_of_bold_in_text != -1:
            # The headline is either beginning or ending with bold text in this chunk
            if self._reasoning_headline_chunk is None:
                # If we don't have a headline, we should start reading it
                remaining_text = summary_text_chunk[index_of_bold_in_text + 2 :]  # Remove the ** from start
                # Check if there's another ** in the remaining text (complete headline in one chunk)
                end_index = remaining_text.find("**")
                if end_index != -1:
                    # Complete headline in one chunk
                    self._last_reasoning_headline = remaining_text[:end_index]
                    return self._last_reasoning_headline
                else:
                    # Start of headline, continue chunking
                    self._reasoning_headline_chunk = remaining_text
            else:
                # If we already have a headline, it means we should wrap up
                self._reasoning_headline_chunk += summary_text_chunk[:index_of_bold_in_text]  # Remove the ** from end
                self._last_reasoning_headline = self._reasoning_headline_chunk
                self._reasoning_headline_chunk = None
                return self._last_reasoning_headline
        elif self._reasoning_headline_chunk is not None:
            # No bold text in this chunk, so we should just add the text to the headline
            self._reasoning_headline_chunk += summary_text_chunk

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

        if self._mode == AssistantMode.ASSISTANT:
            await database_sync_to_async(report_user_action)(
                self._user,
                "chat with ai",
                {
                    "prompt": self._latest_message.content if self._latest_message else None,
                    "output": output,
                    "response": visualization_response,
                },
            )
        elif self._mode == AssistantMode.INSIGHTS_TOOL and self._tool_call_partial_state:
            await database_sync_to_async(report_user_action)(
                self._user,
                "standalone ai tool call",
                {
                    "prompt": self._tool_call_partial_state.root_tool_insight_plan,
                    "output": output,
                    "response": visualization_response,
                    "tool_name": "create_and_query_insight",
                },
            )

    @asynccontextmanager
    async def _lock_conversation(self):
        try:
            self._conversation.status = Conversation.Status.IN_PROGRESS
            await self._conversation.asave(update_fields=["status"])
            yield
        finally:
            self._conversation.status = Conversation.Status.IDLE
            await self._conversation.asave(update_fields=["status", "updated_at"])
