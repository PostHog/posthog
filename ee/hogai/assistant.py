from collections.abc import AsyncGenerator, Generator, Iterator
from functools import partial
from typing import Any, Literal, Optional, TypedDict, TypeGuard, Union

from asgiref.sync import sync_to_async
from langchain_core.messages import AIMessageChunk
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
from ee.hogai.utils import AssistantNodeName, AssistantState, Conversation
from posthog.event_usage import report_user_action
from posthog.models import Team, User
from posthog.schema import (
    AssistantEventType,
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
    AssistantMessage,
    FailureMessage,
    HumanMessage,
    RouterMessage,
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

NODE_TO_REASONING_MESSAGE: dict[AssistantNodeName, str] = {
    AssistantNodeName.ROUTER: "Identifying type of analysis",
    AssistantNodeName.TRENDS_PLANNER: "Picking relevant events and properties",
    AssistantNodeName.FUNNEL_PLANNER: "Picking relevant events and properties",
    AssistantNodeName.TRENDS_GENERATOR: "Creating trends query",
    AssistantNodeName.FUNNEL_GENERATOR: "Creating funnel query",
}


class Assistant:
    _team: Team
    _graph: CompiledStateGraph
    _user: Optional[User]
    _conversation: Conversation

    def __init__(self, team: Team, conversation: Conversation, user: Optional[User] = None):
        self._team = team
        self._user = user
        self._conversation = conversation
        self._graph = AssistantGraph(team).compile_full_graph()
        self._chunks = AIMessageChunk(content="")

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
        callbacks = [langfuse_handler] if langfuse_handler else []
        generator: Iterator[Any] = self._graph.stream(
            self._initial_state,
            config={"recursion_limit": 24, "callbacks": callbacks},
            stream_mode=["messages", "values", "updates", "debug"],
        )

        # Send a chunk to establish the connection avoiding the worker's timeout.
        yield self._serialize_message(AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.ACK))

        try:
            last_viz_message = None
            for update in generator:
                if message := self._process_update(update):
                    if isinstance(message, VisualizationMessage):
                        last_viz_message = message
                    yield self._serialize_message(message)
            self._report_conversation(last_viz_message)
        except:
            # This is an unhandled error, so we just stop further generation at this point
            yield self._serialize_message(FailureMessage())
            raise  # Re-raise, so that the error is printed or goes into Sentry

    @property
    def _initial_state(self) -> AssistantState:
        messages = [message.root for message in self._conversation.messages]
        return {"messages": messages, "intermediate_steps": None, "plan": None}

    def _process_update(self, update: Any) -> BaseModel | None:
        if is_value_update(update):
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
                        return VisualizationMessage(answer=parsed_message.answer)
                elif langgraph_state["langgraph_node"] == AssistantNodeName.SUMMARIZER:
                    self._chunks += langchain_message  # type: ignore
                    return AssistantMessage(content=self._chunks.content)
        elif is_task_started_update(update):
            _, task_update = update
            node_name = task_update["payload"]["name"]  # type: ignore
            if reasoning_message := NODE_TO_REASONING_MESSAGE.get(node_name):
                return ReasoningMessage(content=reasoning_message)
        return None

    def _serialize_message(self, message: BaseModel) -> str:
        output = ""
        if isinstance(message, AssistantGenerationStatusEvent):
            output += f"event: {AssistantEventType.STATUS}\n"
        else:
            output += f"event: {AssistantEventType.MESSAGE}\n"
        return output + f"data: {message.model_dump_json(exclude_none=True)}\n\n"

    def _report_conversation(self, message: Optional[VisualizationMessage]):
        human_message: VisualizationMessage | AssistantMessage | HumanMessage | FailureMessage | RouterMessage = (
            self._conversation.messages[-1].root
        )
        if self._user and message and isinstance(human_message, HumanMessage):
            report_user_action(
                self._user,
                "chat with ai",
                {"prompt": human_message.content, "response": message.model_dump_json(exclude_none=True)},
            )
