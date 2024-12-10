from collections.abc import AsyncGenerator, Generator, Iterator
from functools import partial
from typing import Any, Literal, Optional, TypedDict, TypeGuard, Union, cast
from uuid import uuid4

from asgiref.sync import sync_to_async
from django.forms import ValidationError
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
from ee.hogai.utils import AssistantNodeName, AssistantState, Conversation, ReplaceMessages
from ee.models import AssistantThread
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


def is_value_update(update: list[Any]) -> TypeGuard[tuple[Literal["values"], dict[AssistantNodeName, AssistantState]]]:
    """
    Transition between nodes.
    """
    return len(update) == 2 and update[0] == "updates"


class LangGraphState(TypedDict):
    langgraph_node: AssistantNodeName


def is_message_update(
    update: list[Any],
) -> TypeGuard[tuple[Literal["messages"], tuple[Union[AIMessageChunk, Any], LangGraphState]]]:
    """
    Streaming of messages. Returns a partial state.
    """
    return len(update) == 2 and update[0] == "messages"


def is_state_update(update: list[Any]) -> TypeGuard[tuple[Literal["updates"], AssistantState]]:
    """
    Update of the state.
    """
    return len(update) == 2 and update[0] == "values"


def is_task_started_update(
    update: list[Any],
) -> TypeGuard[tuple[Literal["messages"], tuple[Union[AIMessageChunk, Any], LangGraphState]]]:
    """
    Streaming of messages. Returns a partial state.
    """
    return len(update) == 2 and update[0] == "debug" and update[1]["type"] == "task"


VISUALIZATION_NODES: dict[AssistantNodeName, type[SchemaGeneratorNode]] = {
    AssistantNodeName.TRENDS_GENERATOR: TrendsGeneratorNode,
    AssistantNodeName.FUNNEL_GENERATOR: FunnelGeneratorNode,
}


class Assistant:
    _team: Team
    _graph: CompiledStateGraph
    _user: Optional[User]
    _conversation: Conversation
    _state: Optional[AssistantState]

    def __init__(self, team: Team, conversation: Conversation, user: Optional[User] = None):
        self._team = team
        self._user = user
        self._conversation = conversation
        self._graph = AssistantGraph(team).compile_full_graph()
        self._chunks = AIMessageChunk(content="")
        self._state = None

    def stream(self):
        if SERVER_GATEWAY_INTERFACE == "ASGI":
            return self._astream()
        return self._stream()

    async def _astream(self) -> AsyncGenerator[str, None]:
        generator = self._stream()
        while True:
            try:
                if message := await sync_to_async(partial(next, generator), thread_sensitive=False)():
                    yield message
            except StopIteration:
                break

    def _stream(self) -> Generator[str, None, None]:
        thread, last_message = self._init_thread()
        state = self._init_or_update_state(thread)
        config = self._get_config(thread)

        generator: Iterator[Any] = self._graph.stream(
            state, config=config, stream_mode=["messages", "values", "updates", "debug"]
        )

        # Send the last message with the initialized id.
        yield self._serialize_message(last_message)

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
                yield self._serialize_message(AssistantMessage(content=state.tasks[0].interrupts[0].value, done=True))
            else:
                self._report_conversation(last_viz_message)
        except:
            # This is an unhandled error, so we just stop further generation at this point
            yield self._serialize_message(FailureMessage())
            raise  # Re-raise, so that the error is printed or goes into Sentry

    @property
    def _initial_state(self) -> AssistantState:
        messages = [message.root for message in self._conversation.messages]
        return {
            "messages": messages,
            "intermediate_steps": None,
            "start_idx": len(messages) - 1,
            "plan": None,
        }

    def _get_config(self, thread: AssistantThread) -> RunnableConfig:
        callbacks = [langfuse_handler] if langfuse_handler else []
        config: RunnableConfig = {
            "recursion_limit": 24,
            "callbacks": callbacks,
            "configurable": {"thread_id": thread.id},
        }
        return config

    def _init_or_update_state(self, thread: AssistantThread):
        config = self._get_config(thread)
        snapshot = self._graph.get_state(config)
        if snapshot.next:
            saved_state = cast(AssistantState, snapshot.values)
            self._state = saved_state
            intermediate_steps = saved_state.get("intermediate_steps")
            if intermediate_steps:
                last_message = self._conversation.messages[-1].root
                if isinstance(last_message, HumanMessage):
                    intermediate_steps = intermediate_steps.copy()
                    intermediate_steps[-1] = (intermediate_steps[-1][0], last_message.content)
                    self._graph.update_state(
                        config,
                        {
                            "messages": ReplaceMessages(self._conversation.messages),
                            "intermediate_steps": intermediate_steps,
                        },
                    )
            return None
        initial_state = self._initial_state
        self._state = initial_state
        return initial_state

    def _init_thread(self):
        thread, _ = AssistantThread.objects.get_or_create(
            id=self._conversation.session_id, team=self._team, user=self._user
        )
        last_message = self._conversation.messages[-1].root
        if isinstance(last_message, HumanMessage):
            last_message.id = uuid4()
        else:
            raise ValidationError("The last message must be a human message.")
        return thread, last_message

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
                    if intermediate_steps := input.get("intermediate_steps"):
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
            self._state = update[1]
        elif is_value_update(update):
            _, state_update = update

            if AssistantNodeName.ROUTER in state_update and "messages" in state_update[AssistantNodeName.ROUTER]:
                return state_update[AssistantNodeName.ROUTER]["messages"][0]
            elif intersected_nodes := state_update.keys() & VISUALIZATION_NODES.keys():
                # Reset chunks when schema validation fails.
                self._chunks = AIMessageChunk(content="")

                node_name = intersected_nodes.pop()
                if "messages" in state_update[node_name]:
                    return state_update[node_name]["messages"][0]
                elif state_update[node_name].get("intermediate_steps", []):
                    return AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.GENERATION_ERROR)
            elif AssistantNodeName.SUMMARIZER in state_update:
                self._chunks = AIMessageChunk(content="")
                return state_update[AssistantNodeName.SUMMARIZER]["messages"][0]
        elif is_message_update(update):
            langchain_message, langgraph_state = update[1]
            if isinstance(langchain_message, AIMessageChunk):
                if langgraph_state["langgraph_node"] in VISUALIZATION_NODES.keys():
                    self._chunks += langchain_message  # type: ignore
                    parsed_message = VISUALIZATION_NODES[langgraph_state["langgraph_node"]].parse_output(
                        self._chunks.tool_calls[0]["args"]
                    )
                    if parsed_message:
                        initiator_idx = self._state.get("start_idx") if self._state is not None else None
                        return VisualizationMessage(answer=parsed_message.query, initiator=initiator_idx)
                elif langgraph_state["langgraph_node"] == AssistantNodeName.SUMMARIZER:
                    self._chunks += langchain_message  # type: ignore
                    return AssistantMessage(content=self._chunks.content)
        elif is_task_started_update(update):
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

    def _report_conversation(self, message: Optional[VisualizationMessage]):
        human_message = self._conversation.messages[-1].root
        if self._user and message and isinstance(human_message, HumanMessage):
            report_user_action(
                self._user,
                "chat with ai",
                {"prompt": human_message.content, "response": message.model_dump_json(exclude_none=True)},
            )
