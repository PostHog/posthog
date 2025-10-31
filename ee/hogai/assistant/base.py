from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, Literal, Optional, cast, get_args
from uuid import UUID, uuid4

import structlog
import posthoganalytics
from asgiref.sync import async_to_sync
from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.messages import AIMessageChunk
from langchain_core.runnables.config import RunnableConfig
from langgraph.errors import GraphRecursionError
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StreamMode
from posthoganalytics.ai.langchain.callbacks import CallbackHandler

from posthog.schema import (
    AssistantEventType,
    AssistantGenerationStatusEvent,
    AssistantMessage,
    AssistantUpdateEvent,
    FailureMessage,
    HumanMessage,
    MaxBillingContext,
)

from posthog import event_usage
from posthog.event_usage import report_user_action
from posthog.models import Team, User
from posthog.sync import database_sync_to_async

from ee.hogai.graph.base.node import BaseAssistantNode
from ee.hogai.utils.exceptions import GenerationCanceled
from ee.hogai.utils.helpers import extract_stream_update
from ee.hogai.utils.state import (
    GraphValueUpdateTuple,
    is_message_update,
    is_state_update,
    is_value_update,
    validate_state_update,
)
from ee.hogai.utils.stream_processor import AssistantStreamProcessor
from ee.hogai.utils.types import AssistantMessageUnion, AssistantOutput
from ee.hogai.utils.types.base import AssistantDispatcherEvent, AssistantMode, AssistantResultUnion, MessageChunkAction
from ee.hogai.utils.types.composed import AssistantMaxGraphState, AssistantMaxPartialGraphState, MaxNodeName
from ee.models import Conversation

logger = structlog.get_logger(__name__)


class BaseAssistant(ABC):
    _team: Team
    _graph: CompiledStateGraph
    _user: User
    _state_type: type[AssistantMaxGraphState]
    _partial_state_type: type[AssistantMaxPartialGraphState]
    _mode: AssistantMode
    _contextual_tools: dict[str, Any]
    _conversation: Conversation
    _session_id: Optional[str]
    _latest_message: Optional[HumanMessage]
    _state: Optional[AssistantMaxGraphState]
    _callback_handler: Optional[BaseCallbackHandler]
    _trace_id: Optional[str | UUID]
    _billing_context: Optional[MaxBillingContext]
    _initial_state: Optional[AssistantMaxGraphState | AssistantMaxPartialGraphState]
    _stream_processor: AssistantStreamProcessor
    """The stream processor that processes dispatcher actions and message chunks."""

    def __init__(
        self,
        team: Team,
        conversation: Conversation,
        *,
        new_message: Optional[HumanMessage] = None,
        user: User,
        graph: CompiledStateGraph,
        state_type: type[AssistantMaxGraphState],
        partial_state_type: type[AssistantMaxPartialGraphState],
        mode: AssistantMode,
        session_id: Optional[str] = None,
        contextual_tools: Optional[dict[str, Any]] = None,
        is_new_conversation: bool = False,
        trace_id: Optional[str | UUID] = None,
        billing_context: Optional[MaxBillingContext] = None,
        initial_state: Optional[AssistantMaxGraphState | AssistantMaxPartialGraphState] = None,
        callback_handler: Optional[BaseCallbackHandler] = None,
    ):
        self._team = team
        self._contextual_tools = contextual_tools or {}
        self._user = user
        self._session_id = session_id
        self._conversation = conversation
        self._latest_message = new_message.model_copy(deep=True, update={"id": str(uuid4())}) if new_message else None
        self._is_new_conversation = is_new_conversation
        self._state = None
        self._graph = graph
        self._state_type = state_type
        self._partial_state_type = partial_state_type
        self._callback_handler = callback_handler or (
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
        self._billing_context = billing_context
        self._mode = mode
        self._initial_state = initial_state
        # Initialize the stream processor with node configuration
        self._stream_processor = AssistantStreamProcessor(
            streaming_nodes=self.STREAMING_NODES,
            visualization_nodes=self.VISUALIZATION_NODES,
        )

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

    @abstractmethod
    def get_initial_state(self) -> AssistantMaxGraphState:
        """The initial state of the graph."""
        pass

    @abstractmethod
    def get_resumed_state(self) -> AssistantMaxPartialGraphState:
        """The state of the graph after a resume."""
        pass

    async def ainvoke(self) -> list[tuple[Literal[AssistantEventType.MESSAGE], AssistantMessageUnion]]:
        """Returns all messages at once without streaming."""
        messages: list[tuple[Literal[AssistantEventType.MESSAGE], AssistantMessageUnion]] = []

        async for event_type, message in self.astream(
            stream_message_chunks=False, stream_first_message=False, stream_only_assistant_messages=True
        ):
            messages.append(
                (cast(Literal[AssistantEventType.MESSAGE], event_type), cast(AssistantMessageUnion, message))
            )
        return messages

    @async_to_sync
    async def invoke(self) -> list[tuple[Literal[AssistantEventType.MESSAGE], AssistantMessageUnion]]:
        """Sync method. Returns all messages in once without streaming."""
        return await self.ainvoke()

    async def astream(
        self,
        stream_message_chunks: bool = True,
        stream_subgraphs: bool = True,
        stream_first_message: bool = True,
        stream_only_assistant_messages: bool = False,
    ) -> AsyncGenerator[AssistantOutput, None]:
        state = await self._init_or_update_state()
        config = self._get_config()

        stream_mode: list[StreamMode] = ["values", "updates", "custom"]
        if stream_message_chunks:
            stream_mode.append("messages")

        generator: AsyncIterator[Any] = self._graph.astream(
            state, config=config, stream_mode=stream_mode, subgraphs=stream_subgraphs
        )

        async with self._lock_conversation():
            # Assign the conversation id to the client.
            if not stream_only_assistant_messages and self._is_new_conversation:
                yield AssistantEventType.CONVERSATION, self._conversation

            if stream_first_message and self._latest_message:
                # Send the latest received human message with the initialized id.
                yield AssistantEventType.MESSAGE, self._latest_message

            try:
                async for update in generator:
                    if messages := await self._process_update(update):
                        for message in messages:
                            if isinstance(message, get_args(AssistantMessageUnion)):
                                message = cast(AssistantMessageUnion, message)
                                yield AssistantEventType.MESSAGE, message

                            if stream_only_assistant_messages:
                                continue

                            if isinstance(message, AssistantGenerationStatusEvent):
                                yield AssistantEventType.STATUS, message
                            elif isinstance(message, AssistantUpdateEvent):
                                yield AssistantEventType.UPDATE, message

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
                    state_snapshot = validate_state_update(snapshot.values, self._state_type)
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
        saved_state = validate_state_update(snapshot.values, self._state_type)
        last_recorded_dt = saved_state.start_dt

        # Add existing ids to streamed messages, so we don't send the messages again.
        for message in saved_state.messages:
            if message.id is not None:
                self._stream_processor._streamed_update_ids.add(message.id)

        # Add the latest message id to streamed messages, so we don't send it multiple times.
        if self._latest_message and self._latest_message.id is not None:
            self._stream_processor._streamed_update_ids.add(self._latest_message.id)

        # If the graph previously hasn't reset the state, it is an interrupt. We resume from the point of interruption.
        if snapshot.next and self._latest_message and saved_state.graph_status == "interrupted":
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
                setattr(initial_state, key, value)

        # Reset the start_dt if the conversation has been running for more than 5 minutes.
        # Helps to keep the cache.
        if last_recorded_dt is not None:
            if datetime.now() - last_recorded_dt > timedelta(minutes=5):
                initial_state.start_dt = datetime.now()
        # No recorded start_dt, so we set it to the current time.
        else:
            initial_state.start_dt = datetime.now()

        self._state = initial_state
        return initial_state

    async def _process_update(self, update: Any) -> list[AssistantResultUnion] | None:
        update = extract_stream_update(update)

        new_message: AssistantResultUnion | None = None
        if not isinstance(update, AssistantDispatcherEvent):
            if is_state_update(update):
                _, new_state = update
                self._state = validate_state_update(new_state, self._state_type)
            elif is_value_update(update) and (new_message := await self._aprocess_value_update(update)):
                return [new_message]

            if is_message_update(update):
                # Convert the message chunk update to a dispatcher event to prepare for a bright future without LangGraph
                message, state = update[1]
                if not isinstance(message, AIMessageChunk):
                    return None
                update = AssistantDispatcherEvent(
                    action=MessageChunkAction(message=message), node_name=state["langgraph_node"]
                )

        if isinstance(update, AssistantDispatcherEvent) and (new_message := self._stream_processor.process(update)):
            return [new_message] if new_message else None

        return None

    async def _aprocess_value_update(self, update: GraphValueUpdateTuple) -> AssistantResultUnion | None:
        return None

    def _build_root_config_for_persistence(self) -> RunnableConfig:
        """
        Return a RunnableConfig that forces checkpoint writes onto the root conversation namespace.
        Streaming messages may originate from nested subgraphs. By pinning the `checkpoint_ns`
        to root, we ensure the partial update lands on the root graph so that persisted chunks are
        discoverable when the conversation state is rehydrated later.
        """
        return {
            "configurable": {
                "thread_id": self._conversation.id,
                # Force root graph to avoid subgraph namespaces when persisting mid-stream
                "checkpoint_ns": "",
            }
        }

    async def _report_conversation_state(
        self,
        event_name: str,
        properties: dict[str, Any],
    ):
        if not self._user:
            return
        await database_sync_to_async(report_user_action)(
            self._user,
            event_name,
            properties,
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
