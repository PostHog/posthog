"""
Base Assistant architecture for the AI Assistant system.

This module defines the abstract base class and factory pattern that replaces
the monolithic Assistant class with a more modular approach.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
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

from ee.hogai.processors.update_processor import GraphUpdateProcessor
from ee.hogai.utils.types import BaseState
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
)
from ee.hogai.utils.types import (
    AssistantMessageOrStatusUnion,
    AssistantMessageUnion,
    AssistantOutput,
)
from ee.models import Conversation
from posthog.models import Team, User
from posthog.schema import (
    AssistantEventType,
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
    AssistantMessage,
    AssistantMessageType,
    FailureMessage,
    HumanMessage,
    MaxBillingContext,
    VisualizationMessage,
)

logger = structlog.get_logger(__name__)


class BaseAssistant(ABC):
    """
    Abstract base class for all assistant types.

    Each assistant type (main, insights, memory, etc.) extends this base class
    and implements graph-specific behavior.
    """

    _team: Team
    _user: User
    _conversation: Conversation
    _session_id: Optional[str]
    _latest_message: Optional[HumanMessage]
    _state: Optional[BaseState]
    _callback_handler: Optional[BaseCallbackHandler]
    _trace_id: Optional[str | UUID]
    _custom_update_ids: set[str]
    _reasoning_headline_chunk: Optional[str]
    _last_reasoning_headline: Optional[str]
    _billing_context: Optional[MaxBillingContext]
    _is_new_conversation: bool
    _contextual_tools: dict[str, Any]
    _chunks: AIMessageChunk

    def __init__(
        self,
        team: Team,
        conversation: Conversation,
        *,
        new_message: Optional[HumanMessage] = None,
        user: User,
        session_id: Optional[str] = None,
        contextual_tools: Optional[dict[str, Any]] = None,
        is_new_conversation: bool = False,
        trace_id: Optional[str | UUID] = None,
        billing_context: Optional[MaxBillingContext] = None,
    ):
        self._team = team
        self._user = user
        self._conversation = conversation
        self._session_id = session_id
        self._latest_message = new_message.model_copy(deep=True, update={"id": str(uuid4())}) if new_message else None
        self._is_new_conversation = is_new_conversation
        self._contextual_tools = contextual_tools or {}
        self._state = None
        self._callback_handler = (
            CallbackHandler(
                posthoganalytics.default_client,
                distinct_id=user.distinct_id if user else None,
                properties={
                    "conversation_id": str(self._conversation.id),
                    "is_first_conversation": is_new_conversation,
                    "$session_id": self._session_id,
                    "assistant_type": self.__class__.__name__,
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
        self._chunks = AIMessageChunk(content="")

    @abstractmethod
    def _create_graph(self) -> CompiledStateGraph:
        """Create and compile the graph specific to this assistant type."""
        pass

    @abstractmethod
    def _get_update_processor(self) -> Optional[GraphUpdateProcessor]:
        """Get the update processor for this assistant's graph."""
        pass

    @abstractmethod
    async def _init_or_update_state(self) -> Optional[BaseState]:
        """Initialize or update the state for this assistant."""
        pass

    @abstractmethod
    async def _report_conversation_state(
        self,
        last_assistant_message: AssistantMessage | None = None,
        last_visualization_message: VisualizationMessage | None = None,
    ):
        """Report conversation state for analytics."""
        pass

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
        """Stream assistant responses."""
        graph = self._create_graph()
        state = await self._init_or_update_state()
        config = self._get_config()

        # Some execution modes don't need to stream messages.
        stream_mode: list[StreamMode] = ["values", "updates", "debug", "custom"]
        if stream_messages:
            stream_mode.append("messages")

        generator = graph.astream(state, config=config, stream_mode=stream_mode, subgraphs=True)

        async with self._lock_conversation():
            # Assign the conversation id to the client.
            if self._is_new_conversation:
                yield AssistantEventType.CONVERSATION, self._conversation

            if self._latest_message and self._should_send_initial_message():
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
                state = await graph.aget_state(config)
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

                    await graph.aupdate_state(
                        config,
                        self._create_interrupt_state(interrupt_messages),
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
                await graph.aupdate_state(config, self._get_reset_state())

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
                    snapshot = await graph.aget_state(config)
                    state_snapshot = validate_state_update(snapshot.values)
                    # Some nodes might have already sent a failure message, so we don't want to send another one.
                    if not state_snapshot.messages or not isinstance(state_snapshot.messages[-1], FailureMessage):
                        yield AssistantEventType.MESSAGE, FailureMessage()
            finally:
                await self._report_conversation_state(
                    last_assistant_message=last_ai_message, last_visualization_message=last_viz_message
                )

    @abstractmethod
    def _should_send_initial_message(self) -> bool:
        """Whether to send the initial message (graph-specific)."""
        pass

    @abstractmethod
    def _create_interrupt_state(self, interrupt_messages: list[AssistantMessage]) -> BaseState:
        """Create state for interrupt handling (graph-specific)."""
        pass

    @abstractmethod
    def _get_reset_state(self) -> BaseState:
        """Get reset state for error recovery (graph-specific)."""
        pass

    def _get_config(self) -> RunnableConfig:
        """Get LangGraph runnable config."""
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
                    "assistant_type": self.__class__.__name__,
                    "tag": "max_ai",
                },
            },
        }
        return config

    async def _process_update(self, update: Any) -> list[BaseModel] | None:
        """Process graph updates using the appropriate processor."""
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
        """Process value updates - can be overridden by subclasses."""
        processor = self._get_update_processor()
        if processor:
            return processor.process_value_update(update)
        return [AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.ACK)]

    def _process_message_update(self, update: GraphMessageUpdateTuple) -> BaseModel | None:
        """Process message updates - can be overridden by subclasses."""
        processor = self._get_update_processor()
        if processor:
            return processor.process_message_update(update)
        return None

    async def _process_task_started_update(self, update: GraphTaskStartedUpdateTuple) -> BaseModel | None:
        """Process task started updates using graph processor."""
        _, task_update = update
        node_name = task_update["payload"]["name"]  # type: ignore

        processor = self._get_update_processor()
        if processor and self._state:
            return await processor.get_reasoning_message(node_name, self._state)
        return None

    @asynccontextmanager
    async def _lock_conversation(self):
        """Lock conversation during processing."""
        try:
            self._conversation.status = Conversation.Status.IN_PROGRESS
            await self._conversation.asave(update_fields=["status"])
            yield
        finally:
            self._conversation.status = Conversation.Status.IDLE
            await self._conversation.asave(update_fields=["status", "updated_at"])
