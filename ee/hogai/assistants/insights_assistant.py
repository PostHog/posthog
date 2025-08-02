"""
Insights Assistant implementation.

This assistant handles dedicated insights generation workflows using the
InsightsAssistantGraph and InsightsGraphState.
"""

from typing import Optional, Any
from uuid import UUID

from langgraph.graph.state import CompiledStateGraph

from ee.hogai.assistants.base_assistant import BaseAssistant
from ee.hogai.graph import InsightsAssistantGraph
from ee.hogai.processors.update_processor import GraphUpdateProcessor
from ee.hogai.states.graph_states import InsightsGraphState, PartialInsightsGraphState
from posthog.schema import AssistantMessage, HumanMessage, MaxBillingContext, VisualizationMessage
from posthog.sync import database_sync_to_async
from posthog.event_usage import report_user_action


class InsightsAssistant(BaseAssistant):
    """
    Insights assistant specialized for query generation and insights creation.

    This assistant uses the InsightsAssistantGraph and InsightsGraphState
    for focused insights workflows.
    """

    _tool_call_partial_state: Optional[Any]

    def __init__(
        self,
        team,
        conversation,
        *,
        new_message: Optional[HumanMessage] = None,
        user,
        session_id: Optional[str] = None,
        contextual_tools: Optional[dict[str, Any]] = None,
        is_new_conversation: bool = False,
        trace_id: Optional[str | UUID] = None,
        tool_call_partial_state: Optional[Any] = None,
        billing_context: Optional[MaxBillingContext] = None,
    ):
        super().__init__(
            team=team,
            conversation=conversation,
            new_message=new_message,
            user=user,
            session_id=session_id,
            contextual_tools=contextual_tools,
            is_new_conversation=is_new_conversation,
            trace_id=trace_id,
            billing_context=billing_context,
        )
        self._tool_call_partial_state = tool_call_partial_state

    def _create_graph(self) -> CompiledStateGraph:
        """Create the insights assistant graph."""
        return InsightsAssistantGraph(self._team, self._user).compile_full_graph()

    def _get_update_processor(self) -> Optional[GraphUpdateProcessor]:
        """Get the update processor for the insights graph."""
        from ee.hogai.factories.processor_factory import UpdateProcessorFactory

        return UpdateProcessorFactory.create_insights_processor(self._team, self._user)

    async def _init_or_update_state(self) -> Optional[InsightsGraphState]:
        """Initialize or update the insights state."""
        graph = self._create_graph()
        config = self._get_config()
        snapshot = await graph.aget_state(config)

        # Handle interrupt resumption
        if snapshot.next and self._latest_message:
            # The MigratingDjangoCheckpointer already handled migration when loading the checkpoint
            # so snapshot.values is always a dict that can be validated into the correct state type
            saved_state = InsightsGraphState.model_validate(snapshot.values)

            if saved_state.graph_status == "interrupted":
                self._state = saved_state
                await graph.aupdate_state(
                    config,
                    PartialInsightsGraphState(
                        messages=[self._latest_message], graph_status="resumed", query_generation_retry_count=0
                    ),
                )
                return None

        # Create initial insights state
        if self._latest_message:
            initial_state = InsightsGraphState(
                messages=[self._latest_message],
                query_generation_retry_count=0,
                graph_status=None,
            )
        else:
            initial_state = InsightsGraphState(messages=[])

        # Apply tool call partial state if provided
        if self._tool_call_partial_state:
            # Check if it's AssistantState and extract relevant fields
            if hasattr(self._tool_call_partial_state, "root_tool_insight_plan"):
                initial_state.root_tool_insight_plan = self._tool_call_partial_state.root_tool_insight_plan
            if hasattr(self._tool_call_partial_state, "root_tool_insight_type"):
                initial_state.root_tool_insight_type = self._tool_call_partial_state.root_tool_insight_type

        self._state = initial_state
        return initial_state

    def _should_send_initial_message(self) -> bool:
        """Insights assistant typically doesn't send initial message (called as tool)."""
        return False

    def _create_interrupt_state(self, interrupt_messages: list[AssistantMessage]) -> PartialInsightsGraphState:
        """Create interrupt state for insights assistant."""
        return PartialInsightsGraphState(
            messages=interrupt_messages,
            graph_status="interrupted",
        )

    def _get_reset_state(self) -> PartialInsightsGraphState:
        """Get reset state for error recovery."""
        return PartialInsightsGraphState.get_reset_state()

    async def _report_conversation_state(
        self,
        last_assistant_message: AssistantMessage | None = None,
        last_visualization_message: VisualizationMessage | None = None,
    ):
        """Report conversation state for insights assistant analytics."""
        if not self._user:
            return

        visualization_response = (
            last_visualization_message.model_dump_json(exclude_none=True) if last_visualization_message else None
        )
        output = last_assistant_message.content if isinstance(last_assistant_message, AssistantMessage) else None

        if self._tool_call_partial_state:
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
