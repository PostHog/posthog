from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal, Optional, cast, get_args
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from products.slack_app.backend.slack_thread import SlackThreadContext

import structlog
import posthoganalytics
from asgiref.sync import async_to_sync
from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.runnables.config import RunnableConfig
from langgraph.errors import GraphInterrupt, GraphRecursionError
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, StreamMode
from posthoganalytics.ai.langchain.callbacks import CallbackHandler

from posthog.schema import (
    AssistantEventType,
    AssistantGenerationStatusEvent,
    AssistantMessage,
    AssistantToolCallMessage,
    AssistantUpdateEvent,
    FailureMessage,
    HumanMessage,
    MaxBillingContext,
    MultiQuestionForm,
    SubagentUpdateEvent,
)

from posthog import event_usage
from posthog.cloud_utils import is_cloud
from posthog.event_usage import report_user_action
from posthog.models import Team, User
from posthog.ph_client import get_client
from posthog.sync import database_sync_to_async
from posthog.utils import get_instance_region

from ee.hogai.core.base import BaseAssistantGraph
from ee.hogai.core.stream_processor import AssistantStreamProcessorProtocol
from ee.hogai.tool import ApprovalRequest
from ee.hogai.utils.exceptions import (
    LLM_API_EXCEPTIONS,
    LLM_CLIENT_ERROR_COUNTER,
    LLM_CLIENT_EXCEPTIONS,
    LLM_PROVIDER_ERROR_COUNTER,
    LLM_TRANSIENT_EXCEPTIONS,
    GenerationCanceled,
)
from ee.hogai.utils.feature_flags import is_privacy_mode_enabled
from ee.hogai.utils.helpers import extract_stream_update
from ee.hogai.utils.state import validate_state_update
from ee.hogai.utils.types.base import (
    ApprovalPayload,
    AssistantDispatcherEvent,
    AssistantOutput,
    AssistantResultUnion,
    AssistantStreamedMessageUnion,
    LangGraphUpdateEvent,
)
from ee.hogai.utils.types.composed import AssistantMaxGraphState, AssistantMaxPartialGraphState
from ee.models import Conversation

logger = structlog.get_logger(__name__)


class SubagentCallbackHandler(CallbackHandler):
    """
    Callback handler for subagents that makes all events appear as children of a parent span.

    This ensures that when a subagent runs, its trace events are emitted as $ai_span (children)
    rather than $ai_trace (root), keeping all subagent activity nested under the parent tool's span.

    Works by overriding _get_parent_run_id to return the parent span ID for root-level runs,
    which is used by _capture_trace_or_span to determine the event type.
    """

    _parent_span_id: UUID

    def __init__(self, *args, parent_span_id: str | UUID, **kwargs):
        super().__init__(*args, **kwargs)
        self._parent_span_id = UUID(str(parent_span_id)) if isinstance(parent_span_id, str) else parent_span_id

    def _get_parent_run_id(self, trace_id, run_id: UUID, parent_run_id: Optional[UUID]):
        # Return parent span ID for root-level runs, making them emit $ai_span instead of $ai_trace
        if parent_run_id is None:
            return self._parent_span_id
        return super()._get_parent_run_id(trace_id, run_id, parent_run_id)


class BaseAgentRunner(ABC):
    _team: Team
    _graph: CompiledStateGraph
    _user: User
    _state_type: type[AssistantMaxGraphState]
    _partial_state_type: type[AssistantMaxPartialGraphState]
    _contextual_tools: dict[str, Any]
    _conversation: Conversation
    _session_id: Optional[str]
    _latest_message: Optional[HumanMessage | AssistantToolCallMessage]
    _state: Optional[AssistantMaxGraphState]
    _callback_handlers: list[BaseCallbackHandler]
    _trace_id: Optional[str | UUID]
    _billing_context: Optional[MaxBillingContext]
    _initial_state: Optional[AssistantMaxGraphState | AssistantMaxPartialGraphState]
    _stream_processor: AssistantStreamProcessorProtocol
    _use_checkpointer: bool
    _parent_span_id: Optional[str | UUID]
    _slack_thread_context: Optional["SlackThreadContext"]
    _is_agent_billable: bool
    _resume_payload: Optional[dict[str, Any]]

    def __init__(
        self,
        team: Team,
        conversation: Conversation,
        *,
        new_message: Optional[HumanMessage] = None,
        user: User,
        graph_class: type[BaseAssistantGraph],
        state_type: type[AssistantMaxGraphState],
        partial_state_type: type[AssistantMaxPartialGraphState],
        session_id: Optional[str] = None,
        contextual_tools: Optional[dict[str, Any]] = None,
        is_new_conversation: bool = False,
        trace_id: Optional[str | UUID] = None,
        parent_span_id: Optional[str | UUID] = None,
        billing_context: Optional[MaxBillingContext] = None,
        initial_state: Optional[AssistantMaxGraphState | AssistantMaxPartialGraphState] = None,
        callback_handler: Optional[BaseCallbackHandler] = None,
        use_checkpointer: bool = True,
        stream_processor: AssistantStreamProcessorProtocol,
        slack_thread_context: Optional["SlackThreadContext"] = None,
        is_agent_billable: bool = True,
        resume_payload: Optional[dict[str, Any]] = None,
    ):
        self._team = team
        self._contextual_tools = contextual_tools or {}
        self._user = user
        self._session_id = session_id
        self._conversation = conversation
        self._latest_message = new_message.model_copy(deep=True, update={"id": str(uuid4())}) if new_message else None
        self._is_new_conversation = is_new_conversation
        self._state = None
        self._state_type = state_type
        self._partial_state_type = partial_state_type
        self._use_checkpointer = use_checkpointer
        # Set the checkpointer to None to use the global checkpointer, if the agent uses a checkpointer, otherwise set it to False.
        graph = graph_class(team, user).compile_full_graph(checkpointer=None if self._use_checkpointer else False)
        self._graph = graph

        self._callback_handlers = []
        if callback_handler:
            self._callback_handlers.append(callback_handler)
        else:

            def init_handler(client: posthoganalytics.Client):
                callback_properties = {
                    "conversation_id": str(self._conversation.id),
                    "$ai_session_id": str(self._conversation.id),
                    "is_first_conversation": is_new_conversation,
                    "$session_id": self._session_id,
                    "is_subagent": not self._use_checkpointer,
                    "$groups": event_usage.groups(team=team),
                    "ai_support_impersonated": not is_agent_billable,
                    "ai_product": "posthog_ai",
                }
                # Use SubagentCallbackHandler when parent_span_id is provided to nest all events under the parent
                if parent_span_id:
                    return SubagentCallbackHandler(
                        client,
                        distinct_id=user.distinct_id if user else None,
                        properties=callback_properties,
                        trace_id=trace_id,
                        privacy_mode=is_privacy_mode_enabled(team),
                        parent_span_id=parent_span_id,
                    )
                return CallbackHandler(
                    client,
                    distinct_id=user.distinct_id if user else None,
                    properties=callback_properties,
                    trace_id=trace_id,
                    privacy_mode=is_privacy_mode_enabled(team),
                )

            # Local deployment or hobby
            if not is_cloud() and (local_client := posthoganalytics.default_client):
                self._callback_handlers.append(init_handler(local_client))
            elif region := get_instance_region():
                # Add regional client first
                self._callback_handlers.append(init_handler(get_client(region)))
                # If we're in EU, add the US client as well, so we can see US and EU traces
                if region == "EU":
                    self._callback_handlers.append(init_handler(get_client("US")))

        self._trace_id = trace_id
        self._parent_span_id = parent_span_id
        self._billing_context = billing_context
        self._initial_state = initial_state
        self._is_agent_billable = is_agent_billable
        # Initialize the stream processor with node configuration
        self._stream_processor = stream_processor
        self._slack_thread_context = slack_thread_context
        self._resume_payload = resume_payload

    @abstractmethod
    def get_initial_state(self) -> AssistantMaxGraphState:
        """The initial state of the graph."""
        pass

    @abstractmethod
    def get_resumed_state(self) -> AssistantMaxPartialGraphState:
        """The state of the graph after a resume."""
        pass

    async def ainvoke(self) -> list[tuple[Literal[AssistantEventType.MESSAGE], AssistantStreamedMessageUnion]]:
        """Returns all messages at once without streaming."""
        messages: list[tuple[Literal[AssistantEventType.MESSAGE], AssistantStreamedMessageUnion]] = []

        async for event_type, message in self.astream(
            stream_message_chunks=False, stream_first_message=False, stream_only_assistant_messages=True
        ):
            messages.append(
                (cast(Literal[AssistantEventType.MESSAGE], event_type), cast(AssistantStreamedMessageUnion, message))
            )
        return messages

    @async_to_sync
    async def invoke(self) -> list[tuple[Literal[AssistantEventType.MESSAGE], AssistantStreamedMessageUnion]]:
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

        stream_mode: list[StreamMode] = ["values", "custom"]
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
                            if isinstance(message, get_args(AssistantStreamedMessageUnion)):
                                message = cast(AssistantStreamedMessageUnion, message)
                                yield AssistantEventType.MESSAGE, message

                            if stream_only_assistant_messages:
                                continue

                            if isinstance(message, AssistantGenerationStatusEvent):
                                yield AssistantEventType.STATUS, message
                            elif isinstance(message, AssistantUpdateEvent | SubagentUpdateEvent):
                                yield AssistantEventType.UPDATE, message
            except GraphInterrupt:
                # GraphInterrupt is raised when interrupt() is called in a tool.
                # TRICKY: don't reset state. The interrupt handling code
                # below will process the interrupt via aget_state().
                pass
            except GraphRecursionError:
                recursion_limit_message = AssistantMessage(
                    content="I've reached the maximum number of steps. Would you like me to continue?",
                    id=str(uuid4()),
                )
                yield AssistantEventType.MESSAGE, recursion_limit_message

                if self._use_checkpointer:
                    await self._graph.aupdate_state(
                        config,
                        self._partial_state_type(messages=[recursion_limit_message]),
                    )
                return  # Don't run interrupt handling after recursion error
            except LLM_CLIENT_EXCEPTIONS as e:
                # Client/validation errors (400, 422) - these won't resolve on retry
                if self._use_checkpointer:
                    await self._graph.aupdate_state(config, self._partial_state_type.get_reset_state())
                provider = type(e).__module__.partition(".")[0] or "unknown_provider"
                LLM_CLIENT_ERROR_COUNTER.labels(provider=provider).inc()
                logger.exception("llm_client_error", error=str(e), provider=provider)
                posthoganalytics.capture_exception(
                    e,
                    distinct_id=self._user.distinct_id if self._user else None,
                    properties={
                        "error_type": "llm_client_error",
                        "provider": provider,
                        "tag": "max_ai",
                    },
                )
                yield (
                    AssistantEventType.MESSAGE,
                    FailureMessage(
                        content="I'm unable to process this request. The conversation may be too long. Please start a new conversation.",
                        id=str(uuid4()),
                    ),
                )
                return  # Don't run interrupt handling after client errors
            except LLM_TRANSIENT_EXCEPTIONS as e:
                # Transient errors (5xx, rate limits, timeouts) - may resolve on retry
                if self._use_checkpointer:
                    await self._graph.aupdate_state(config, self._partial_state_type.get_reset_state())
                provider = type(e).__module__.partition(".")[0] or "unknown_provider"
                LLM_PROVIDER_ERROR_COUNTER.labels(provider=provider).inc()
                logger.exception("llm_provider_error", error=str(e), provider=provider)
                posthoganalytics.capture_exception(
                    e,
                    distinct_id=self._user.distinct_id if self._user else None,
                    properties={
                        "error_type": "llm_provider_error",
                        "provider": provider,
                        "tag": "max_ai",
                    },
                )
                yield (
                    AssistantEventType.MESSAGE,
                    FailureMessage(
                        content="I'm unable to respond right now due to a temporary service issue. Please try again later.",
                        id=str(uuid4()),
                    ),
                )
                return  # Don't run interrupt handling after LLM errors
            except LLM_API_EXCEPTIONS as e:
                # Catch-all for other API errors (auth errors, etc.)
                if self._use_checkpointer:
                    await self._graph.aupdate_state(config, self._partial_state_type.get_reset_state())
                provider = type(e).__module__.partition(".")[0] or "unknown_provider"
                LLM_PROVIDER_ERROR_COUNTER.labels(provider=provider).inc()
                logger.exception("llm_api_error", error=str(e), provider=provider)
                posthoganalytics.capture_exception(
                    e,
                    distinct_id=self._user.distinct_id if self._user else None,
                    properties={
                        "error_type": "llm_api_error",
                        "provider": provider,
                        "tag": "max_ai",
                    },
                )
                yield (
                    AssistantEventType.MESSAGE,
                    FailureMessage(
                        content="I'm unable to respond right now. Please try again later.",
                        id=str(uuid4()),
                    ),
                )
                return  # Don't run interrupt handling after LLM errors
            except Exception as e:
                if self._use_checkpointer:
                    # Reset the state, so that the next generation starts from the beginning.
                    await self._graph.aupdate_state(config, self._partial_state_type.get_reset_state())

                if not isinstance(e, GenerationCanceled):
                    logger.exception("Error in assistant stream", error=e)
                    self._capture_exception(e)

                    # This is an unhandled error, so we just stop further generation at this point
                    if self._use_checkpointer:
                        snapshot = await self._graph.aget_state(config)
                        state_snapshot = validate_state_update(snapshot.values, self._state_type)
                        # Some nodes might have already sent a failure message, so we don't want to send another one.
                        if not state_snapshot.messages or not isinstance(state_snapshot.messages[-1], FailureMessage):
                            yield AssistantEventType.MESSAGE, FailureMessage()
                return  # Don't run interrupt handling after errors

            # Interrupt handling - runs after normal completion or GraphInterrupt
            if not self._use_checkpointer:
                # Subagents don't use the checkpointer, and we don't need to do interrupt handling.
                return

            # Check if the assistant has requested help.
            state = await self._graph.aget_state(config)

            # If graph completed successfully (no pending nodes) and we were previously interrupted,
            # reset graph_status so the next message can start fresh instead of trying to resume.
            if not state.next:
                current_state = validate_state_update(state.values, self._state_type)
                if current_state.graph_status == "interrupted":
                    await self._graph.aupdate_state(
                        config,
                        self._partial_state_type(graph_status=""),
                    )

            if state.next:
                interrupt_messages: list[Any] = []
                should_not_update_state = False
                for task in state.tasks:
                    for interrupt in task.interrupts:
                        if interrupt.value is None:
                            continue  # Skip None interrupts
                        # Reconstruct interrupt message based on its type
                        interrupt_message: Any
                        if isinstance(interrupt.value, str):
                            interrupt_message = AssistantMessage(content=interrupt.value, id=str(uuid4()))
                            interrupt_messages.append(interrupt_message)
                            yield AssistantEventType.MESSAGE, interrupt_message
                        elif isinstance(interrupt.value, MultiQuestionForm):
                            # No need to yield a message here - the form will be displayed to the user through the tool call args
                            # and the answers comes through the tool call result ui_payload
                            should_not_update_state = True
                        elif isinstance(interrupt.value, ApprovalRequest):
                            # Check if this is an ApprovalRequest from interrupt() in a tool
                            should_not_update_state = True
                            # Stream approval event directly
                            message_id = str(uuid4())
                            approval_payload = ApprovalPayload(
                                proposal_id=interrupt.value.proposal_id,
                                decision_status="pending",
                                tool_name=interrupt.value.tool_name,
                                preview=interrupt.value.preview,
                                payload=interrupt.value.payload,
                                original_tool_call_id=interrupt.value.original_tool_call_id,
                                message_id=message_id,
                            )
                            yield AssistantEventType.APPROVAL, approval_payload
                            # Store approval card metadata for persistence (page reload)
                            await self._store_approval_card_data(approval_payload)
                        else:
                            interrupt_message = interrupt.value
                            interrupt_messages.append(interrupt_message)
                            yield AssistantEventType.MESSAGE, interrupt_message

                # TRICKY: For approval interrupts, we intentionally do NOT call aupdate_state().
                if should_not_update_state:
                    return

                # For other interrupts (NodeInterrupt), update state
                state_update = self._partial_state_type(
                    messages=interrupt_messages,
                    graph_status="interrupted",
                )
                await self._graph.aupdate_state(config, state_update)

    def _get_config(self) -> RunnableConfig:
        config: RunnableConfig = {
            "recursion_limit": 96,
            "callbacks": self._callback_handlers,
            "configurable": {
                "thread_id": self._conversation.id,
                "trace_id": self._trace_id,
                "session_id": self._session_id,
                "distinct_id": self._user.distinct_id if self._user else None,
                "contextual_tools": self._contextual_tools,
                "team": self._team,
                "user": self._user,
                "billing_context": self._billing_context,
                "is_subagent": not self._use_checkpointer,
                "slack_thread_context": self._slack_thread_context,
                "is_agent_billable": self._is_agent_billable,
                # Metadata to be sent to PostHog SDK (error tracking, etc).
                "sdk_metadata": {
                    "tag": "max_ai",
                },
            },
        }
        return config

    async def _init_or_update_state(self):
        config = self._get_config()

        last_recorded_dt = None
        if self._use_checkpointer:
            snapshot = await self._graph.aget_state(config)
            saved_state = validate_state_update(snapshot.values, self._state_type)
            last_recorded_dt = saved_state.start_dt

            # Add existing ids to streamed messages, so we don't send the messages again.
            for message in saved_state.messages:
                if message.id is not None:
                    self._stream_processor.mark_id_as_streamed(message.id)

            # If there are pending nodes (snapshot.next is non-empty), we need to resume.
            # This happens when:
            # 1. A tool called interrupt() for approval - snapshot.next will have pending nodes
            # 2. A NodeInterrupt was raised - graph_status will be "interrupted"
            if snapshot.next:
                self._state = saved_state
                if self._resume_payload:
                    # Resume with the payload using LangGraph's Command
                    # The interrupt() call will return this payload value

                    # Update approval_decisions status if this is an approval/rejection response
                    await self._update_approval_decision_status(self._resume_payload)

                    # If there's a new message alongside the resume (user sent message while approval pending),
                    # include it in the state update so the agent sees it as a proper HumanMessage
                    if self._latest_message:
                        return Command(resume=self._resume_payload, update={"messages": [self._latest_message]})
                    return Command(resume=self._resume_payload)
                elif saved_state.graph_status == "interrupted":
                    # NodeInterrupt without approval flow - add the new message and resume
                    if self._latest_message:
                        await self._graph.aupdate_state(
                            config,
                            self.get_resumed_state(),
                        )
                    return None
                elif self._latest_message:
                    # Pending nodes but user sent a new message without resume_payload.
                    # This could be cancelled execution or user abandoning an approval interrupt.
                    # Start fresh with the new message.
                    pass  # Fall through to return initial state
                else:
                    # Pending nodes but no resume_payload, not interrupted, and no new message.
                    # This means an approval interrupt is waiting for user input.
                    # Return None to resume from checkpoint
                    return None

        # Add the latest message id to streamed messages, so we don't send it multiple times.
        if self._latest_message and self._latest_message.id is not None:
            self._stream_processor.mark_id_as_streamed(self._latest_message.id)

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

        if not isinstance(update, AssistantDispatcherEvent):
            if updates := await self._stream_processor.process_langgraph_update(LangGraphUpdateEvent(update=update)):
                return updates
        elif new_message := await self._stream_processor.process(update):
            return new_message

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
        # Subagents (use_checkpointer=False) share the conversation with the parent agent.
        # They should not update the conversation status to avoid race conditions and
        # thread executor issues when multiple activities run in parallel.
        if not self._use_checkpointer:
            yield
            return

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

    async def _store_approval_card_data(self, approval: ApprovalPayload) -> None:
        """
        Store approval card metadata in conversation.approval_decisions.

        TRICKY: when we call aupdate_state(), LangGraph creates a NEW checkpoint. This new checkpoint
        does NOT preserve the pending nodes from snapshot.next, which breaks the resume flow:
        - On resume, we check if snapshot.next has pending nodes
        - If empty (because aupdate_state cleared it), we start a new graph execution
        - This causes the tool to call interrupt() again with a new proposal_id
        Solution: Store approval card metadata in a side-channel (conversation.approval_decisions)
        and have the ConversationSerializer reconstruct the data when loading the conversation.

        NOTE: We intentionally do NOT store 'payload' here. The payload is stored in the LangGraph
        checkpoint's interrupt value (single source of truth). The serializer fetches it from there.
        """
        # Only store if not already in approval_decisions (don't overwrite resolved status)
        if approval.proposal_id in self._conversation.approval_decisions:
            return

        # Store with "pending" decision_status - updated to approved/rejected when user responds
        # Payload is NOT stored here - it lives in the checkpoint interrupt (single source of truth)
        self._conversation.approval_decisions[approval.proposal_id] = {
            "decision_status": "pending",
            "tool_name": approval.tool_name,
            "preview": approval.preview,
            "message_id": approval.message_id,
            "original_tool_call_id": approval.original_tool_call_id,
        }
        await self._conversation.asave(update_fields=["approval_decisions"])

    async def _update_approval_decision_status(self, resume_payload: dict[str, Any]) -> None:
        """
        Update the approval_decisions status when user approves or rejects.
        """
        action = resume_payload.get("action")
        proposal_id = resume_payload.get("proposal_id")

        if not action or not proposal_id:
            return

        if proposal_id not in self._conversation.approval_decisions:
            return

        status = "approved" if action == "approve" else "rejected" if action == "reject" else None
        if not status:
            return

        self._conversation.approval_decisions[proposal_id]["decision_status"] = status
        await self._conversation.asave(update_fields=["approval_decisions"])
