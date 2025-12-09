from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID, uuid4

import structlog
from posthoganalytics import capture_exception

from posthog.schema import AgentMode, AssistantMessage, ContextMessage, HumanMessage, MaxBillingContext

from posthog.models import Team, User

from ee.hogai.chat_agent import AssistantGraph
from ee.hogai.chat_agent.stream_processor import ChatAgentStreamProcessor
from ee.hogai.chat_agent.taxonomy.types import TaxonomyNodeName
from ee.hogai.context.prompts import BROWSER_SESSION_CLOSED_PROMPT
from ee.hogai.core.runner import BaseAgentRunner
from ee.hogai.tools.browser import BrowserSessionManager
from ee.hogai.utils.types import AssistantNodeName, AssistantOutput, AssistantState, PartialAssistantState
from ee.models import Conversation

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from ee.hogai.utils.types.composed import MaxNodeName


STREAMING_NODES: set["MaxNodeName"] = {
    AssistantNodeName.ROOT,
    AssistantNodeName.INKEEP_DOCS,
    AssistantNodeName.MEMORY_ONBOARDING,
    AssistantNodeName.MEMORY_INITIALIZER,
    AssistantNodeName.MEMORY_ONBOARDING_ENQUIRY,
    AssistantNodeName.MEMORY_ONBOARDING_FINALIZE,
    AssistantNodeName.DASHBOARD_CREATION,
}


VERBOSE_NODES: set["MaxNodeName"] = {
    AssistantNodeName.TRENDS_GENERATOR,
    AssistantNodeName.FUNNEL_GENERATOR,
    AssistantNodeName.RETENTION_GENERATOR,
    AssistantNodeName.SQL_GENERATOR,
    AssistantNodeName.INSIGHTS_SEARCH,
    AssistantNodeName.QUERY_EXECUTOR,
    AssistantNodeName.MEMORY_INITIALIZER_INTERRUPT,
    AssistantNodeName.ROOT,
    AssistantNodeName.ROOT_TOOLS,
    AssistantNodeName.SLASH_COMMAND_HANDLER,
    TaxonomyNodeName.TOOLS_NODE,
    TaxonomyNodeName.TASK_EXECUTOR,
}


class ChatAgentRunner(BaseAgentRunner):
    _state: AssistantState | None
    _initial_state: AssistantState | PartialAssistantState | None
    _selected_agent_mode: AgentMode | None

    def __init__(
        self,
        team: Team,
        conversation: Conversation,
        *,
        new_message: HumanMessage | None = None,
        user: User,
        session_id: str | None = None,
        contextual_tools: dict[str, Any] | None = None,
        is_new_conversation: bool = False,
        trace_id: Optional[str | UUID] = None,
        parent_span_id: Optional[str | UUID] = None,
        billing_context: Optional[MaxBillingContext] = None,
        initial_state: Optional[AssistantState | PartialAssistantState] = None,
        agent_mode: AgentMode | None = None,
        use_checkpointer: bool = True,
    ):
        super().__init__(
            team,
            conversation,
            new_message=new_message,
            user=user,
            graph_class=AssistantGraph,
            state_type=AssistantState,
            partial_state_type=PartialAssistantState,
            session_id=session_id,
            contextual_tools=contextual_tools,
            is_new_conversation=is_new_conversation,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            initial_state=initial_state,
            billing_context=billing_context,
            use_checkpointer=use_checkpointer,
            stream_processor=ChatAgentStreamProcessor(
                verbose_nodes=VERBOSE_NODES,
                streaming_nodes=STREAMING_NODES,
                state_type=AssistantState,
                team=team,
                user=user,
            ),
        )
        self._selected_agent_mode = agent_mode

    def get_initial_state(self) -> AssistantState:
        if self._latest_message:
            new_state = AssistantState(
                messages=[self._latest_message],
                start_id=self._latest_message.id,
                query_generation_retry_count=0,
                graph_status=None,
                rag_context=None,
            )
            # Only set the agent mode if it was explicitly set.
            if self._selected_agent_mode:
                new_state.agent_mode = self._selected_agent_mode
            return new_state

        # When resuming, do not set the mode. It should start from the same mode as the previous generation.
        return AssistantState(messages=[])

    def get_resumed_state(self) -> PartialAssistantState:
        if not self._latest_message:
            return PartialAssistantState(messages=[])
        new_state = PartialAssistantState(
            messages=[self._latest_message], graph_status="resumed", query_generation_retry_count=0
        )
        # Only set the agent mode if it was explicitly set.
        if self._selected_agent_mode:
            new_state.agent_mode = self._selected_agent_mode
        return new_state

    async def astream(
        self,
        stream_message_chunks: bool = True,
        stream_subgraphs: bool = True,
        stream_first_message: bool = True,
        stream_only_assistant_messages: bool = False,
    ) -> AsyncGenerator[AssistantOutput, None]:
        last_ai_message: AssistantMessage | None = None
        async for stream_event in super().astream(
            stream_message_chunks, stream_subgraphs, stream_first_message, stream_only_assistant_messages
        ):
            _, message = stream_event
            if isinstance(message, AssistantMessage):
                last_ai_message = message
            yield stream_event

        if not self._use_checkpointer:
            # we don't want to track subagent conversations
            return

        output = last_ai_message.content if isinstance(last_ai_message, AssistantMessage) else None
        await self._report_conversation_state(
            "chat with ai",
            {
                "prompt": self._latest_message.content if self._latest_message else None,
                "output": output,
                "is_new_conversation": self._is_new_conversation,
                "$session_id": self._session_id,
            },
        )

    @asynccontextmanager
    async def _lock_conversation(self):
        """
        Override to add browser session cleanup when the conversation turn ends.
        This ensures the browser session is closed even if the generator is stopped early.
        """
        try:
            self._conversation.status = Conversation.Status.IN_PROGRESS
            await self._conversation.asave(update_fields=["status"])
            yield
        finally:
            # Clean up browser session before releasing the conversation lock
            await self._cleanup_browser_session()
            self._conversation.status = Conversation.Status.IDLE
            await self._conversation.asave(update_fields=["status", "updated_at"])

    async def _cleanup_browser_session(self) -> None:
        """
        Close any active browser session for this conversation and add a context message
        to inform the agent that the session was closed.
        """
        conversation_id = str(self._conversation.id)
        # Check if there's an active browser session for this conversation
        if conversation_id not in BrowserSessionManager._sessions:
            return

        try:
            # Close the browser session
            await BrowserSessionManager.close(conversation_id)
            # Add a system message to the state to inform the agent
            # This will be visible in the next turn
            config = self._get_config()
            await self._graph.aupdate_state(
                config,
                PartialAssistantState(
                    messages=[ContextMessage(content=BROWSER_SESSION_CLOSED_PROMPT, id=str(uuid4()))],
                ),
            )
        except Exception as e:
            capture_exception(e)
