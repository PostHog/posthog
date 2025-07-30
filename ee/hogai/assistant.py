from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Generic, Literal, Optional, TypeVar, cast
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
    InsightsAssistantGraph,
)
from ee.hogai.utils.exceptions import GenerationCanceled
from ee.hogai.utils.state import (
    is_message_update,
    is_state_update,
    is_task_started_update,
    is_value_update,
    validate_state_update,
)
from ee.hogai.utils.types import (
    AssistantMessageOrStatusUnion,
    AssistantMessageUnion,
    AssistantMode,
    AssistantOutput,
    AssistantState,
    BaseAssistantState,
    BasePartialAssistantState,
    PartialAssistantState,
)
from ee.models import Conversation
from posthog.event_usage import report_user_action
from posthog.models import Team, User
from posthog.schema import (
    AssistantEventType,
    AssistantMessage,
    AssistantMessageType,
    FailureMessage,
    HumanMessage,
    VisualizationMessage,
)
from posthog.sync import database_sync_to_async

logger = structlog.get_logger(__name__)

# Some shared assistant state that all assistants have.
AssistantStateType = TypeVar("AssistantStateType", bound=BaseAssistantState)
PartialAssistantStateType = TypeVar("PartialAssistantStateType", bound=BasePartialAssistantState)


class Assistant(Generic[AssistantStateType, PartialAssistantStateType]):
    _team: Team
    _graph: CompiledStateGraph
    _user: User
    _contextual_tools: dict[str, Any]
    _conversation: Conversation
    _session_id: Optional[str]
    _latest_message: Optional[HumanMessage]
    _state: Optional[AssistantStateType]
    _callback_handler: Optional[BaseCallbackHandler]
    _trace_id: Optional[str | UUID]
    _custom_update_ids: set[str]
    _reasoning_headline_chunk: Optional[str]
    """Like a message chunk, but specifically for the reasoning headline (and just a plain string)."""
    _last_reasoning_headline: Optional[str]
    """Last emittted reasoning headline, to be able to carry it over."""

    def __init__(
        self,
        state_type: type[AssistantStateType],
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
        tool_call_partial_state: Optional[PartialAssistantStateType] = None,
    ):
        self._state_type = state_type
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
                await self._graph.aupdate_state(config, self._state_type.get_reset_state())

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
                    state_snapshot = validate_state_update(snapshot.values)
                    # Some nodes might have already sent a failure message, so we don't want to send another one.
                    if not state_snapshot.messages or not isinstance(state_snapshot.messages[-1], FailureMessage):
                        yield AssistantEventType.MESSAGE, FailureMessage()
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
                # Metadata to be sent to PostHog SDK (error tracking, etc).
                "sdk_metadata": {
                    "assistant_mode": self._mode.value,
                    "tag": "max_ai",
                },
            },
        }
        return config

    # Can be an abstract method or a method of the State class
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
                    PartialAssistantState(
                        messages=[self._latest_message], graph_status="resumed", query_generation_retry_count=0
                    ),
                )
                # Return None to indicate that we want to continue the execution from the interrupted point.
                return None

        # Append the new message and reset some fields to their default values.
        if self._latest_message and self._mode == AssistantMode.ASSISTANT:
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

    async def _process_update(self, update: Any) -> list[BaseModel] | None:
        if update[1] == "custom":
            # Custom streams come from a tool call
            update = update[2]
        update = update[1:]  # we remove the first element, which is the node/subgraph node name
        if is_state_update(update):
            _, new_state = update
            self._state = validate_state_update(new_state)
        elif is_value_update(update) and (new_messages := self.graph.process_value_update(update)):
            return new_messages
        elif is_message_update(update) and (new_message := self.graph.process_message_update(update)):
            return [new_message]
        elif is_task_started_update(update) and (new_message := await self.graph.process_task_started_update(update)):
            return [new_message]
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
