from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from posthog.schema import AgentMode, AssistantMessage, HumanMessage, MaxBillingContext, PermissionStatus

from posthog.models import Team, User

from ee.hogai.chat_agent import AssistantGraph
from ee.hogai.chat_agent.stream_processor import ChatAgentStreamProcessor
from ee.hogai.chat_agent.taxonomy.types import TaxonomyNodeName
from ee.hogai.core.runner import BaseAgentRunner
from ee.hogai.utils.helpers import find_last_message_of_type
from ee.hogai.utils.types import AssistantNodeName, AssistantOutput, AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import ReplaceMessages
from ee.models import Conversation

if TYPE_CHECKING:
    from products.slack_app.backend.slack_thread import SlackThreadContext

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
    _state: Optional[AssistantState]
    _initial_state: Optional[AssistantState | PartialAssistantState]
    _selected_agent_mode: AgentMode | None

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
        parent_span_id: Optional[str | UUID] = None,
        billing_context: Optional[MaxBillingContext] = None,
        initial_state: Optional[AssistantState | PartialAssistantState] = None,
        agent_mode: AgentMode | None = None,
        slack_thread_context: Optional["SlackThreadContext"] = None,
        use_checkpointer: bool = True,
        is_agent_billable: bool = True,
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
            is_agent_billable=is_agent_billable,
            stream_processor=ChatAgentStreamProcessor(
                verbose_nodes=VERBOSE_NODES,
                streaming_nodes=STREAMING_NODES,
                state_type=AssistantState,
                team=team,
                user=user,
            ),
            slack_thread_context=slack_thread_context,
        )
        self._selected_agent_mode = agent_mode

    def get_initial_state(self) -> AssistantState:
        new_messages = []
        resume_state = None

        # Find messages that requested approval
        # Pseudcode, requires more robust logic
        if self._state and self._state.graph_status == "interrupted":
            resume_state = "resumed"
            new_messages = [*self._state.messages]
            last_assistant_message = find_last_message_of_type(new_messages, AssistantMessage)
            assert last_assistant_message
            for tool_call in last_assistant_message.tool_calls or []:
                # For demo, we deny
                tool_call.permission_status = PermissionStatus.DENIED

        if self._latest_message:
            new_messages.append(self._latest_message)

        if len(new_messages) > 1:
            new_messages = ReplaceMessages(new_messages)

        if self._latest_message:
            new_state = AssistantState(
                messages=new_messages,
                start_id=self._latest_message.id,
                query_generation_retry_count=0,
                rag_context=None,
                graph_status=resume_state,
            )
            # Only set the agent mode if it was explicitly set.
            if self._selected_agent_mode:
                new_state.agent_mode = self._selected_agent_mode
            return new_state

        # When resuming, do not set the mode. It should start from the same mode as the previous generation.
        return AssistantState(messages=new_messages, graph_status=resume_state)

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
                "slack_workspace_domain": self._conversation.slack_workspace_domain,
                "$session_id": self._session_id,
            },
        )
