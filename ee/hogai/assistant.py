import json
from collections.abc import Generator, Iterator
from typing import Any, Optional
from uuid import uuid4

from langchain_core.messages import AIMessageChunk
from langchain_core.runnables.config import RunnableConfig
from langfuse.callback import CallbackHandler
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from ee import settings
from ee.hogai.funnels.nodes import (
    FunnelGeneratorNode,
)
from ee.hogai.graph import AssistantGraph
from ee.hogai.schema_generator.nodes import SchemaGeneratorNode
from ee.hogai.trends.nodes import (
    TrendsGeneratorNode,
)
from ee.hogai.utils.asgi import SyncIterableToAsync
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
from posthog.models import Team, User
from posthog.schema import (
    AssistantEventType,
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
    AssistantMessage,
    FailureMessage,
    HumanMessage,
    ReasoningMessage,
    VisualizationMessage,
)
from posthog.settings import SERVER_GATEWAY_INTERFACE

if settings.LANGFUSE_PUBLIC_KEY:
    langfuse_handler = CallbackHandler(
        public_key=settings.LANGFUSE_PUBLIC_KEY, secret_key=settings.LANGFUSE_SECRET_KEY, host=settings.LANGFUSE_HOST
    )
else:
    langfuse_handler = None


VISUALIZATION_NODES: dict[AssistantNodeName, type[SchemaGeneratorNode]] = {
    AssistantNodeName.TRENDS_GENERATOR: TrendsGeneratorNode,
    AssistantNodeName.FUNNEL_GENERATOR: FunnelGeneratorNode,
}


class Assistant:
    _team: Team
    _graph: CompiledStateGraph
    _user: Optional[User]
    _conversation: Conversation
    _latest_message: HumanMessage
    _state: Optional[AssistantState]

    def __init__(
        self,
        team: Team,
        conversation: Conversation,
        new_message: HumanMessage,
        user: Optional[User] = None,
        is_new_conversation: bool = False,
    ):
        self._team = team
        self._user = user
        self._conversation = conversation
        self._latest_message = new_message.model_copy(deep=True, update={"id": str(uuid4())})
        self._is_new_conversation = is_new_conversation
        self._graph = AssistantGraph(team).compile_full_graph()
        self._chunks = AIMessageChunk(content="")
        self._state = None

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
                yield self._serialize_message(
                    AssistantMessage(content=state.tasks[0].interrupts[0].value, id=str(uuid4()))
                )
            else:
                self._report_conversation_state(last_viz_message)
        except:
            # This is an unhandled error, so we just stop further generation at this point
            yield self._serialize_message(FailureMessage())
            raise  # Re-raise, so that the error is printed or goes into Sentry

    @property
    def _initial_state(self) -> AssistantState:
        return AssistantState(messages=[self._latest_message], start_id=self._latest_message.id)

    def _get_config(self) -> RunnableConfig:
        callbacks = [langfuse_handler] if langfuse_handler else []
        config: RunnableConfig = {
            "recursion_limit": 24,
            "callbacks": callbacks,
            "configurable": {"thread_id": self._conversation.id},
        }
        return config

    def _init_or_update_state(self):
        config = self._get_config()
        snapshot = self._graph.get_state(config)
        if snapshot.next:
            saved_state = validate_state_update(snapshot.values)
            self._state = saved_state
            self._graph.update_state(config, PartialAssistantState(messages=[self._latest_message], resumed=True))

            return None
        initial_state = self._initial_state
        self._state = initial_state
        return initial_state

    def _node_to_reasoning_message(
        self, node_name: AssistantNodeName, input: AssistantState
    ) -> Optional[ReasoningMessage]:
        match node_name:
            case AssistantNodeName.ROUTER:
                return ReasoningMessage(content="Identifying type of analysis")
            case (
                AssistantNodeName.TRENDS_PLANNER
                | AssistantNodeName.TRENDS_PLANNER_TOOLS
                | AssistantNodeName.FUNNEL_PLANNER
                | AssistantNodeName.FUNNEL_PLANNER_TOOLS
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
                return ReasoningMessage(content="Picking relevant events and properties", substeps=substeps)
            case AssistantNodeName.TRENDS_GENERATOR:
                return ReasoningMessage(content="Creating trends query")
            case AssistantNodeName.FUNNEL_GENERATOR:
                return ReasoningMessage(content="Creating funnel query")
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

        if node_val := state_update.get(AssistantNodeName.ROUTER):
            if isinstance(node_val, PartialAssistantState) and node_val.messages:
                return node_val.messages[0]
        elif intersected_nodes := state_update.keys() & VISUALIZATION_NODES.keys():
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
        elif node_val := state_update.get(AssistantNodeName.SUMMARIZER):
            if isinstance(node_val, PartialAssistantState) and node_val.messages:
                self._chunks = AIMessageChunk(content="")
                return node_val.messages[0]

        return None

    def _process_message_update(self, update: GraphMessageUpdateTuple) -> BaseModel | None:
        langchain_message, langgraph_state = update[1]
        if isinstance(langchain_message, AIMessageChunk):
            if langgraph_state["langgraph_node"] in VISUALIZATION_NODES.keys():
                self._chunks += langchain_message  # type: ignore
                parsed_message = VISUALIZATION_NODES[langgraph_state["langgraph_node"]].parse_output(
                    self._chunks.tool_calls[0]["args"]
                )
                if parsed_message:
                    initiator_id = self._state.start_id if self._state is not None else None
                    return VisualizationMessage(answer=parsed_message.query, initiator=initiator_id)
            elif langgraph_state["langgraph_node"] == AssistantNodeName.SUMMARIZER:
                self._chunks += langchain_message  # type: ignore
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
        return output + f"data: {message.model_dump_json(exclude_none=True)}\n\n"

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
