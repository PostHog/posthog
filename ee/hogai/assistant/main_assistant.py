from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from posthog.schema import AssistantMessage, HumanMessage, MaxBillingContext, VisualizationMessage

from posthog.models import Team, User

from ee.hogai.assistant.base import BaseAssistant
from ee.hogai.graph.graph import AssistantGraph
from ee.hogai.graph.taxonomy.types import TaxonomyNodeName
from ee.hogai.utils.stream_processor import AssistantStreamProcessor
from ee.hogai.utils.types import (
    AssistantMode,
    AssistantNodeName,
    AssistantOutput,
    AssistantState,
    PartialAssistantState,
)
from ee.models import Conversation

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
    AssistantNodeName.ROOT_TOOLS,
    TaxonomyNodeName.TOOLS_NODE,
    TaxonomyNodeName.TASK_EXECUTOR,
}


class MainAssistant(BaseAssistant):
    _state: Optional[AssistantState]
    _initial_state: Optional[AssistantState | PartialAssistantState]

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
        initial_state: Optional[AssistantState | PartialAssistantState] = None,
    ):
        super().__init__(
            team,
            conversation,
            new_message=new_message,
            user=user,
            graph=AssistantGraph(team, user).compile_full_graph(),
            state_type=AssistantState,
            partial_state_type=PartialAssistantState,
            mode=AssistantMode.ASSISTANT,
            session_id=session_id,
            contextual_tools=contextual_tools,
            is_new_conversation=is_new_conversation,
            trace_id=trace_id,
            billing_context=billing_context,
            initial_state=initial_state,
            stream_processor=AssistantStreamProcessor(verbose_nodes=VERBOSE_NODES, streaming_nodes=STREAMING_NODES),
        )

    def get_initial_state(self) -> AssistantState:
        if self._latest_message:
            return AssistantState(
                messages=[self._latest_message],
                start_id=self._latest_message.id,
                query_generation_retry_count=0,
                graph_status=None,
                rag_context=None,
            )
        else:
            return AssistantState(messages=[])

    def get_resumed_state(self) -> PartialAssistantState:
        if not self._latest_message:
            return PartialAssistantState(messages=[])
        return PartialAssistantState(
            messages=[self._latest_message], graph_status="resumed", query_generation_retry_count=0
        )

    async def astream(
        self,
        stream_message_chunks: bool = True,
        stream_subgraphs: bool = True,
        stream_first_message: bool = True,
        stream_only_assistant_messages: bool = False,
    ) -> AsyncGenerator[AssistantOutput, None]:
        last_ai_message: AssistantMessage | None = None
        last_viz_message: VisualizationMessage | None = None
        async for stream_event in super().astream(
            stream_message_chunks, stream_subgraphs, stream_first_message, stream_only_assistant_messages
        ):
            _, message = stream_event
            if isinstance(message, VisualizationMessage):
                last_viz_message = message
            if isinstance(message, AssistantMessage):
                last_ai_message = message
            yield stream_event

        visualization_response = last_viz_message.model_dump_json(exclude_none=True) if last_viz_message else None
        output = last_ai_message.content if isinstance(last_ai_message, AssistantMessage) else None
        await self._report_conversation_state(
            "chat with ai",
            {
                "prompt": self._latest_message.content if self._latest_message else None,
                "output": output,
                "response": visualization_response,
                "is_new_conversation": self._is_new_conversation,
            },
        )
