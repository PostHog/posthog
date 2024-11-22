from collections.abc import AsyncGenerator, AsyncIterator, Generator, Iterator
from typing import Any, Literal, Optional, TypedDict, TypeGuard, Union

from langchain_core.messages import AIMessageChunk
from langfuse.callback import CallbackHandler
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel
from sentry_sdk import capture_exception

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


VISUALIZATION_NODES: dict[AssistantNodeName, type[SchemaGeneratorNode]] = {
    AssistantNodeName.TRENDS_GENERATOR: TrendsGeneratorNode,
    AssistantNodeName.FUNNEL_GENERATOR: FunnelGeneratorNode,
}


class Assistant:
    _team: Team
    _graph: CompiledStateGraph
    _chunks: AIMessageChunk

    def __init__(self, team: Team, conversation: Conversation, user: Optional[User] = None):
        self._team = team
        self._conversation = conversation
        self._user = user
        self._graph = AssistantGraph(team).compile_full_graph()
        self._chunks = AIMessageChunk(content="")

    def stream(self) -> Generator[str, None, None] | AsyncGenerator[str, None]:
        if SERVER_GATEWAY_INTERFACE == "ASGI":
            return self._astream()
        return self._stream()

    async def _astream(self) -> AsyncGenerator[BaseModel, None]:
        generator: AsyncIterator[Any] = self._graph.astream(
            self._initial_state,
            config=self._config,
            stream_mode=["messages", "values", "updates"],
        )

        # Send a chunk to establish the connection avoiding the worker's timeout.
        yield AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.ACK)

        try:
            last_message = None
            async for update in generator:
                message = self._process_update(update)
                if message is not None:
                    last_message = message
                    for serialized_message in self._serialize_message(message):
                        yield serialized_message
            self._report_user_action(last_message)
        except Exception as e:
            capture_exception(e)
            yield FailureMessage()  # This is an unhandled error, so we just stop further generation at this point

    def _stream(self) -> Generator[BaseModel, None, None]:
        generator: Iterator[Any] = self._graph.stream(
            self._initial_state,
            config=self._config,
            stream_mode=["messages", "values", "updates"],
        )

        # Send a chunk to establish the connection avoiding the worker's timeout.
        yield AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.ACK)

        try:
            last_message = None
            for update in generator:
                message = self._process_update(update)
                if message is not None:
                    last_message = message
                    yield from self._serialize_message(message)
            self._report_user_action(last_message)
        except Exception as e:
            capture_exception(e)
            yield FailureMessage()  # This is an unhandled error, so we just stop further generation at this point

    @property
    def _initial_state(self) -> AssistantState:
        messages = [message.root for message in self._conversation.messages]
        return {"messages": messages, "intermediate_steps": None, "plan": None}

    @property
    def _config(self) -> dict[str, Any]:
        callbacks = [langfuse_handler] if langfuse_handler else []
        return {"recursion_limit": 24, "callbacks": callbacks}

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
                        return VisualizationMessage(
                            reasoning_steps=parsed_message.reasoning_steps, answer=parsed_message.answer
                        )
                elif langgraph_state["langgraph_node"] == AssistantNodeName.SUMMARIZER:
                    self._chunks += langchain_message  # type: ignore
                    return AssistantMessage(content=self._chunks.content)

    def _serialize_message(self, message: BaseModel):
        if isinstance(message, AssistantGenerationStatusEvent):
            yield f"event: {AssistantEventType.STATUS}\n"
        else:
            yield f"event: {AssistantEventType.MESSAGE}\n"
        yield f"data: {message.model_dump_json(exclude_none=True)}\n\n"

    def _report_user_action(self, last_message: BaseModel):
        human_message = self._conversation.messages[-1].root
        if isinstance(human_message, HumanMessage) and self._user:
            report_user_action(
                self._user,  # type: ignore
                "chat with ai",
                {"prompt": human_message.content, "response": last_message},
            )
