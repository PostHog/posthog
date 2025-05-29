import json
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from typing import Any, Optional, cast
from uuid import UUID, uuid4

import posthoganalytics
import structlog
from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.messages import AIMessageChunk
from langchain_core.runnables.config import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.errors import GraphRecursionError
from posthoganalytics.ai.langchain.callbacks import CallbackHandler
from pydantic import BaseModel

from ee.hogai.graph import (
    AssistantGraph,
    FunnelGeneratorNode,
    MemoryInitializerNode,
    RetentionGeneratorNode,
    SchemaGeneratorNode,
    SQLGeneratorNode,
    TrendsGeneratorNode,
)
from ee.hogai.tool import CONTEXTUAL_TOOL_NAME_TO_TOOL
from ee.hogai.utils.asgi import SyncIterableToAsync
from ee.hogai.utils.exceptions import GenerationCanceled
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
from ee.hogai.utils.types import AssistantNodeName, AssistantState, PartialAssistantState
from ee.models import Conversation
from posthog.event_usage import report_user_action
from posthog.models import Action, Team, User
from posthog.schema import (
    AssistantEventType,
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
    AssistantMessage,
    AssistantToolCallMessage,
    FailureMessage,
    HumanMessage,
    ReasoningMessage,
    VisualizationMessage,
)
from posthog.settings import SERVER_GATEWAY_INTERFACE

VISUALIZATION_NODES: dict[AssistantNodeName, type[SchemaGeneratorNode]] = {
    AssistantNodeName.TRENDS_GENERATOR: TrendsGeneratorNode,
    AssistantNodeName.FUNNEL_GENERATOR: FunnelGeneratorNode,
    AssistantNodeName.RETENTION_GENERATOR: RetentionGeneratorNode,
    AssistantNodeName.SQL_GENERATOR: SQLGeneratorNode,
}

STREAMING_NODES: set[AssistantNodeName] = {
    AssistantNodeName.ROOT,
    AssistantNodeName.INKEEP_DOCS,
    AssistantNodeName.MEMORY_ONBOARDING,
    AssistantNodeName.MEMORY_INITIALIZER,
}
"""Nodes that can stream messages to the client."""


VERBOSE_NODES = STREAMING_NODES | {
    AssistantNodeName.MEMORY_INITIALIZER_INTERRUPT,
    AssistantNodeName.ROOT_TOOLS,
}
"""Nodes that can send messages to the client."""


logger = structlog.get_logger(__name__)


class Assistant:
    _team: Team
    _graph: CompiledStateGraph
    _user: Optional[User]
    _contextual_tools: dict[str, Any]
    _conversation: Conversation
    _latest_message: HumanMessage
    _state: Optional[AssistantState]
    _callback_handler: Optional[BaseCallbackHandler]
    _trace_id: Optional[str | UUID]

    def __init__(
        self,
        team: Team,
        conversation: Conversation,
        new_message: HumanMessage,
        *,
        user: Optional[User] = None,
        contextual_tools: Optional[dict[str, Any]] = None,
        is_new_conversation: bool = False,
        trace_id: Optional[str | UUID] = None,
    ):
        self._team = team
        self._contextual_tools = contextual_tools or {}
        self._user = user
        self._conversation = conversation
        self._latest_message = new_message.model_copy(deep=True, update={"id": str(uuid4())})
        self._is_new_conversation = is_new_conversation
        self._graph = AssistantGraph(team).compile_full_graph()
        self._chunks = AIMessageChunk(content="")
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

    def stream(self):
        if SERVER_GATEWAY_INTERFACE == "ASGI":
            return self._astream()
        return self._stream()

    def _astream(self):
        return SyncIterableToAsync(self._stream())

    def _stream(self) -> Generator[str, None, None]:
        state = self._init_or_update_state()
        config = self._get_config()

        generator: Iterator[Any] = self._graph.stream(
            state, config=config, stream_mode=["messages", "values", "updates", "debug"]
        )

        with self._lock_conversation():
            # Assign the conversation id to the client.
            if self._is_new_conversation:
                yield self._serialize_conversation()

            # Send the last message with the initialized id.
            yield self._serialize_message(self._latest_message)

            try:
                last_viz_message = None
                for update in generator:
                    if message := self._process_update(update):
                        if isinstance(message, VisualizationMessage):
                            last_viz_message = message
                        yield self._serialize_message(message)

                # Check if the assistant has requested help.
                state = self._graph.get_state(config)
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
                            yield self._serialize_message(interrupt_message)

                    self._graph.update_state(
                        config,
                        PartialAssistantState(
                            messages=interrupt_messages,
                            # LangGraph by some reason doesn't store the interrupt exceptions in checkpoints.
                            graph_status="interrupted",
                        ),
                    )
                else:
                    self._report_conversation_state(last_viz_message)
            except GraphRecursionError:
                yield self._serialize_message(
                    FailureMessage(
                        content="The assistant has reached the maximum number of steps. You can explicitly ask to continue.",
                        id=str(uuid4()),
                    )
                )
            except Exception as e:
                # Reset the state, so that the next generation starts from the beginning.
                self._graph.update_state(config, PartialAssistantState.get_reset_state())

                if not isinstance(e, GenerationCanceled):
                    logger.exception("Error in assistant stream", error=e)
                    # This is an unhandled error, so we just stop further generation at this point
                    yield self._serialize_message(FailureMessage())
                    raise  # Re-raise, so that the error is printed or goes into Sentry

    @property
    def _initial_state(self) -> AssistantState:
        return AssistantState(messages=[self._latest_message], start_id=self._latest_message.id)

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
                "team_id": self._team.id,
            },
        }
        return config

    def _init_or_update_state(self):
        config = self._get_config()
        snapshot = self._graph.get_state(config)

        # If the graph previously hasn't reset the state, it is an interrupt. We resume from the point of interruption.
        if snapshot.next:
            saved_state = validate_state_update(snapshot.values)
            if saved_state.graph_status == "interrupted":
                self._state = saved_state
                self._graph.update_state(
                    config, PartialAssistantState(messages=[self._latest_message], graph_status="resumed")
                )
                # Return None to indicate that we want to continue the execution from the interrupted point.
                return None

        initial_state = self._initial_state
        self._state = initial_state
        return initial_state

    def _node_to_reasoning_message(
        self, node_name: AssistantNodeName, input: AssistantState
    ) -> Optional[ReasoningMessage]:
        match node_name:
            case (
                AssistantNodeName.TRENDS_PLANNER
                | AssistantNodeName.TRENDS_PLANNER_TOOLS
                | AssistantNodeName.FUNNEL_PLANNER
                | AssistantNodeName.FUNNEL_PLANNER_TOOLS
                | AssistantNodeName.RETENTION_PLANNER
                | AssistantNodeName.RETENTION_PLANNER_TOOLS
                | AssistantNodeName.SQL_PLANNER
                | AssistantNodeName.SQL_PLANNER_TOOLS
            ):
                substeps: list[str] = []
                if input:
                    if intermediate_steps := input.intermediate_steps:
                        for action, _ in intermediate_steps:
                            match action.tool:
                                case "retrieve_event_properties":
                                    substeps.append(f"Exploring `{action.tool_input}` event's properties")
                                case "retrieve_entity_properties":
                                    substeps.append(f"Exploring {action.tool_input} properties")
                                case "retrieve_event_property_values":
                                    assert isinstance(action.tool_input, dict)
                                    substeps.append(
                                        f"Analyzing `{action.tool_input['property_name']}` event's property `{action.tool_input['event_name']}`"
                                    )
                                case "retrieve_entity_property_values":
                                    assert isinstance(action.tool_input, dict)
                                    substeps.append(
                                        f"Analyzing {action.tool_input['entity']} property `{action.tool_input['property_name']}`"
                                    )
                                case "retrieve_action_properties" | "retrieve_action_property_values":
                                    id = (
                                        action.tool_input
                                        if isinstance(action.tool_input, str)
                                        else action.tool_input["action_id"]
                                    )
                                    try:
                                        action_model = Action.objects.get(pk=id, team__project_id=self._team.project_id)
                                        if action.tool == "retrieve_action_properties":
                                            substeps.append(f"Exploring `{action_model.name}` action properties")
                                        elif action.tool == "retrieve_action_property_values" and isinstance(
                                            action.tool_input, dict
                                        ):
                                            substeps.append(
                                                f"Analyzing `{action.tool_input['property_name']}` action property of `{action_model.name}`"
                                            )
                                    except Action.DoesNotExist:
                                        pass

                return ReasoningMessage(content="Picking relevant events and properties", substeps=substeps)
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
            case _:
                return None

    def _process_update(self, update: Any) -> BaseModel | None:
        if is_state_update(update):
            _, new_state = update
            self._state = validate_state_update(new_state)
        elif is_value_update(update) and (new_message := self._process_value_update(update)):
            return new_message
        elif is_message_update(update) and (new_message := self._process_message_update(update)):
            return new_message
        elif is_task_started_update(update) and (new_message := self._process_task_started_update(update)):
            return new_message
        return None

    def _process_value_update(self, update: GraphValueUpdateTuple) -> BaseModel | None:
        _, maybe_state_update = update
        state_update = validate_value_update(maybe_state_update)

        if intersected_nodes := state_update.keys() & VISUALIZATION_NODES.keys():
            # Reset chunks when schema validation fails.
            self._chunks = AIMessageChunk(content="")

            node_name = intersected_nodes.pop()
            node_val = state_update[node_name]
            if not isinstance(node_val, PartialAssistantState):
                return None
            if node_val.messages:
                return node_val.messages[0]
            elif node_val.intermediate_steps:
                return AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.GENERATION_ERROR)

        for node_name in VERBOSE_NODES:
            if node_val := state_update.get(node_name):
                if isinstance(node_val, PartialAssistantState) and node_val.messages:
                    self._chunks = AIMessageChunk(content="")
                    for candidate_message in node_val.messages:
                        if (
                            # Filter out tool calls without a UI payload
                            not isinstance(candidate_message, AssistantToolCallMessage)
                            or candidate_message.ui_payload is not None
                        ) and (
                            # Also filter out empty assistant messages
                            not isinstance(candidate_message, AssistantMessage)
                            or isinstance(candidate_message, AssistantMessage)
                            and candidate_message.content
                        ):
                            return candidate_message

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
                    return AssistantMessage(content=self._chunks.content)
        return None

    def _process_task_started_update(self, update: GraphTaskStartedUpdateTuple) -> BaseModel | None:
        _, task_update = update
        node_name = task_update["payload"]["name"]  # type: ignore
        node_input = task_update["payload"]["input"]  # type: ignore
        if reasoning_message := self._node_to_reasoning_message(node_name, node_input):
            return reasoning_message
        return None

    def _serialize_message(self, message: BaseModel) -> str:
        output = ""
        if isinstance(message, AssistantGenerationStatusEvent):
            output += f"event: {AssistantEventType.STATUS}\n"
        else:
            output += f"event: {AssistantEventType.MESSAGE}\n"
        return output + f"data: {message.model_dump_json(exclude_none=True, exclude={'tool_calls'})}\n\n"

    def _serialize_conversation(self) -> str:
        output = f"event: {AssistantEventType.CONVERSATION}\n"
        json_conversation = json.dumps({"id": str(self._conversation.id)})
        output += f"data: {json_conversation}\n\n"
        return output

    def _report_conversation_state(self, message: Optional[VisualizationMessage]):
        human_message = self._latest_message
        if self._user and message:
            report_user_action(
                self._user,
                "chat with ai",
                {"prompt": human_message.content, "response": message.model_dump_json(exclude_none=True)},
            )

    @contextmanager
    def _lock_conversation(self):
        try:
            self._conversation.status = Conversation.Status.IN_PROGRESS
            self._conversation.save()
            yield
        finally:
            self._conversation.status = Conversation.Status.IDLE
            self._conversation.save()
