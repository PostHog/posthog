from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal, Optional, cast, get_args
from uuid import UUID, uuid4

import structlog
import posthoganalytics
from asgiref.sync import async_to_sync
from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.messages import AIMessageChunk
from langchain_core.runnables.config import RunnableConfig
from langgraph.errors import GraphRecursionError
from langgraph.types import StreamMode
from posthoganalytics.ai.langchain.callbacks import CallbackHandler
from pydantic import BaseModel

from ee.hogai.graph.base import BaseAssistantNode
from ee.hogai.graph.graph import AssistantCompiledStateGraph
from ee.hogai.utils.exceptions import GenerationCanceled
from ee.hogai.utils.helpers import (
    extract_content_from_ai_message,
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
    validate_state_update,
    validate_value_update,
)
from ee.hogai.utils.types import (
    AssistantMessageOrStatusUnion,
    AssistantMessageUnion,
    AssistantOutput,
)
from ee.hogai.utils.types.base import AssistantMode
from ee.hogai.utils.types.composed import (
    MaxGraphState,
    MaxGraphStateWithMessages,
    MaxNodeName,
    MaxPartialGraphState,
    MaxPartialGraphStateWithMessages,
)
from ee.models import Conversation
from posthog.event_usage import report_user_action
from posthog import event_usage
from posthog.models import Team, User
from posthog.schema import (
    AssistantEventType,
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
    AssistantMessage,
    FailureMessage,
    HumanMessage,
    MaxBillingContext,
    ReasoningMessage,
)
from posthog.sync import database_sync_to_async


logger = structlog.get_logger(__name__)


class BaseAssistant(ABC):
    _team: Team
    _graph: AssistantCompiledStateGraph
    _user: User
    _state_type: type[MaxGraphStateWithMessages]
    _partial_state_type: type[MaxPartialGraphStateWithMessages]
    _mode: AssistantMode
    _contextual_tools: dict[str, Any]
    _conversation: Conversation
    _session_id: Optional[str]
    _latest_message: Optional[HumanMessage]
    _state: Optional[MaxGraphStateWithMessages]
    _callback_handler: Optional[BaseCallbackHandler]
    _trace_id: Optional[str | UUID]
    _custom_update_ids: set[str]
    _reasoning_headline_chunk: Optional[str]
    """Like a message chunk, but specifically for the reasoning headline (and just a plain string)."""
    _last_reasoning_headline: Optional[str]
    """Last emitted reasoning headline, to be able to carry it over."""
    _billing_context: Optional[MaxBillingContext]
    _initial_state: Optional[MaxGraphStateWithMessages | MaxPartialGraphStateWithMessages]

    def __init__(
        self,
        team: Team,
        conversation: Conversation,
        *,
        new_message: Optional[HumanMessage] = None,
        user: User,
        graph: AssistantCompiledStateGraph,
        state_type: type[MaxGraphStateWithMessages],
        partial_state_type: type[MaxPartialGraphStateWithMessages],
        mode: AssistantMode,
        session_id: Optional[str] = None,
        contextual_tools: Optional[dict[str, Any]] = None,
        is_new_conversation: bool = False,
        trace_id: Optional[str | UUID] = None,
        billing_context: Optional[MaxBillingContext] = None,
        initial_state: Optional[MaxGraphStateWithMessages | MaxPartialGraphStateWithMessages] = None,
    ):
        self._team = team
        self._contextual_tools = contextual_tools or {}
        self._user = user
        self._session_id = session_id
        self._conversation = conversation
        self._latest_message = new_message.model_copy(deep=True, update={"id": str(uuid4())}) if new_message else None
        self._is_new_conversation = is_new_conversation
        self._chunks = AIMessageChunk(content="")
        self._state = None
        self._graph = graph
        self._state_type = state_type
        self._partial_state_type = partial_state_type
        self._callback_handler = (
            CallbackHandler(
                posthoganalytics.default_client,
                distinct_id=user.distinct_id if user else None,
                properties={
                    "conversation_id": str(self._conversation.id),
                    "is_first_conversation": is_new_conversation,
                    "$session_id": self._session_id,
                    "assistant_mode": mode.value,
                    "$groups": event_usage.groups(team=team),
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
        self._mode = mode
        self._initial_state = initial_state

    @property
    @abstractmethod
    def VISUALIZATION_NODES(self) -> dict[MaxNodeName, type[BaseAssistantNode]]:
        """Nodes that can generate visualizations."""
        pass

    @property
    @abstractmethod
    def STREAMING_NODES(self) -> set[MaxNodeName]:
        """Nodes that can stream messages to the client."""
        pass

    @property
    @abstractmethod
    def VERBOSE_NODES(self) -> set[MaxNodeName]:
        """Nodes that can send messages to the client."""
        pass

    @property
    @abstractmethod
    def THINKING_NODES(self) -> set[MaxNodeName]:
        """Nodes that pass on thinking messages to the client. Current implementation assumes o3/o4 style of reasoning summaries!"""
        pass

    @abstractmethod
    def get_initial_state(self) -> MaxGraphStateWithMessages:
        """The initial state of the graph."""
        pass

    @abstractmethod
    def get_resumed_state(self) -> MaxPartialGraphStateWithMessages:
        """The state of the graph after a resume."""
        pass

    async def ainvoke(self) -> list[tuple[Literal[AssistantEventType.MESSAGE], AssistantMessageUnion]]:
        """Returns all messages in once without streaming."""
        messages = []

        async for event_type, message in self.astream(stream_messages=False, stream_first_message=False):
            if event_type == AssistantEventType.MESSAGE and not isinstance(
                message, (ReasoningMessage | AssistantGenerationStatusEvent | Conversation)
            ):
                messages.append((event_type, cast(AssistantMessageUnion, message)))

        return messages

    @async_to_sync
    async def invoke(self) -> list[tuple[Literal[AssistantEventType.MESSAGE], AssistantMessageUnion]]:
        """Sync method. Returns all messages in once without streaming."""
        return await self.ainvoke()

    async def astream(
        self, stream_messages: bool = True, stream_subgraphs: bool = True, stream_first_message: bool = True
    ) -> AsyncGenerator[AssistantOutput, None]:
        state = await self._init_or_update_state()
        config = self._get_config()

        # Some execution modes don't need to stream messages.
        stream_mode: list[StreamMode] = ["values", "updates", "debug", "custom"]
        if stream_messages:
            stream_mode.append("messages")

        generator: AsyncIterator[Any] = self._graph.astream(
            state, config=config, stream_mode=stream_mode, subgraphs=stream_subgraphs
        )

        async with self._lock_conversation():
            # Assign the conversation id to the client.
            if self._is_new_conversation:
                yield AssistantEventType.CONVERSATION, self._conversation

            if stream_first_message and self._latest_message:
                # Send the latest received human message with the initialized id.
                yield AssistantEventType.MESSAGE, self._latest_message

            try:
                async for update in generator:
                    if messages := await self._process_update(update):
                        for message in messages:
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
                        self._partial_state_type(
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
                await self._graph.aupdate_state(config, self._partial_state_type.get_reset_state())

                if not isinstance(e, GenerationCanceled):
                    logger.exception("Error in assistant stream", error=e)
                    self._capture_exception(e)

                    # This is an unhandled error, so we just stop further generation at this point
                    snapshot = await self._graph.aget_state(config)
                    state_snapshot = validate_state_update(snapshot.values)
                    # Some nodes might have already sent a failure message, so we don't want to send another one.
                    if not state_snapshot.messages or not isinstance(state_snapshot.messages[-1], FailureMessage):
                        yield AssistantEventType.MESSAGE, FailureMessage()

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
            saved_state = validate_state_update(snapshot.values)
            if saved_state.graph_status == "interrupted":
                self._state = saved_state
                await self._graph.aupdate_state(
                    config,
                    self.get_resumed_state(),
                )
                # Return None to indicate that we want to continue the execution from the interrupted point.
                return None

        initial_state = self.get_initial_state()
        if self._initial_state:
            for key, value in self._initial_state.model_dump(exclude_none=True).items():
                # Don't overwrite messages with an empty list from partial state
                if key == "messages" and value == [] and initial_state.messages:
                    continue
                setattr(initial_state, key, value)
        self._state = initial_state
        return initial_state

    async def _node_to_reasoning_message(
        self, node_name: MaxNodeName, input: MaxGraphStateWithMessages
    ) -> Optional[ReasoningMessage]:
        async_callable = self._graph.get_reasoning_message_by_node_name.get(node_name)
        if async_callable:
            return await async_callable(input, self._last_reasoning_headline or "")
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
        if intersected_nodes := state_update.keys() & self.VISUALIZATION_NODES.keys():
            # Reset chunks when schema validation fails.
            self._chunks = AIMessageChunk(content="")

            node_name: MaxNodeName = intersected_nodes.pop()
            node_val = state_update[node_name]
            if not isinstance(node_val, (MaxGraphState | MaxPartialGraphState)):
                return None
            if node_val.messages:
                return list(node_val.messages)
            elif node_val.intermediate_steps:
                return [AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.GENERATION_ERROR)]

        for node_name in self.VERBOSE_NODES:
            if node_val := state_update.get(node_name):
                if isinstance(node_val, self._partial_state_type) and node_val.messages:
                    self._chunks = AIMessageChunk(content="")
                    _messages: list[BaseModel] = []
                    for candidate_message in node_val.messages:
                        if should_output_assistant_message(candidate_message):
                            _messages.append(candidate_message)
                    return _messages

        for node_name in self.THINKING_NODES:
            if node_val := state_update.get(node_name):
                # If update involves new state from a thinking node, we reset the thinking headline to be sure
                self._reasoning_headline_chunk = None

        return [AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.ACK)]

    def _process_message_update(self, update: GraphMessageUpdateTuple) -> BaseModel | None:
        langchain_message, langgraph_state = update[1]

        # Return ready messages as is
        if isinstance(langchain_message, get_args(AssistantMessageUnion)):
            return langchain_message

        # If not ready message or chunk, return None
        if not isinstance(langchain_message, AIMessageChunk):
            return None

        node_name: MaxNodeName = langgraph_state["langgraph_node"]

        # Check for reasoning content first (for all nodes that support it)
        if reasoning := langchain_message.additional_kwargs.get("reasoning"):
            if reasoning_headline := self._chunk_reasoning_headline(reasoning):
                return ReasoningMessage(content=reasoning_headline)

        # Only process streaming nodes
        if node_name not in self.STREAMING_NODES:
            return None

        # Merge message chunks
        self._merge_message_chunk(langchain_message)

        # Extract and process content
        message_content = extract_content_from_ai_message(self._chunks)
        if not message_content:
            return None

        return AssistantMessage(content=message_content)

    def _merge_message_chunk(self, langchain_message: AIMessageChunk) -> None:
        """Merge a new message chunk with existing chunks, handling content format compatibility.

        # This is because we reset to AIMessageChunk(content="") in a few places,
        # but if we're switching between reasoning and non-reasoning models between different nodes,
        # the format of the content will change, and we need to reset the chunks to the right format.
        """

        current_is_list = isinstance(self._chunks.content, list)
        new_is_list = isinstance(langchain_message.content, list)

        if current_is_list != new_is_list:
            # Content types are incompatible - reset with new chunk
            self._chunks = langchain_message
        else:
            # Compatible types - merge normally
            self._chunks += langchain_message  # type: ignore

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
            self._capture_exception(e)  # not expected, so let's capture
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

    async def _process_task_started_update(self, update: GraphTaskStartedUpdateTuple) -> BaseModel | None:
        _, task_update = update
        node_name = task_update["payload"]["name"]  # type: ignore
        node_input = task_update["payload"]["input"]  # type: ignore

        # First check if this node has a reasoning message in the parent graph
        if reasoning_message := await self._node_to_reasoning_message(node_name, node_input):
            return reasoning_message

        return None

    async def _report_conversation_state(
        self,
        event_name: str,
        event_data: dict[str, Any],
    ):
        if not self._user:
            return
        await database_sync_to_async(report_user_action)(
            self._user,
            event_name,
            event_data,
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

    def _capture_exception(self, e: Exception):
        posthoganalytics.capture_exception(
            e,
            distinct_id=self._user.distinct_id if self._user else None,
            properties={
                "$session_id": self._session_id,
                "$ai_trace_id": self._trace_id,
                "thread_id": self._conversation.id,
                "tag": "max_ai",
                "$groups": event_usage.groups(team=self._team),
            },
        )
