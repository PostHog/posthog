"""
Main Assistant implementation.

This is the primary assistant that handles general conversations and delegates
to specialized subgraphs like insights generation.
"""

from typing import Optional

from langgraph.graph.state import CompiledStateGraph

from ee.hogai.assistants.base_assistant import BaseAssistant
from ee.hogai.graph import AssistantGraph
from ee.hogai.processors.update_processor import GraphUpdateProcessor
from ee.hogai.states.graph_states import AssistantGraphState, PartialAssistantGraphState
from posthog.schema import AssistantMessage, VisualizationMessage
from posthog.sync import database_sync_to_async
from posthog.event_usage import report_user_action


class MainAssistant(BaseAssistant):
    """
    Main assistant that handles general conversations.

    This assistant uses the AssistantGraph and can delegate to subgraphs
    like insights generation, memory management, etc.
    """

    def _create_graph(self) -> CompiledStateGraph:
        """Create the main assistant graph."""
        return AssistantGraph(self._team, self._user).compile_full_graph()

    def _get_update_processor(self) -> Optional[GraphUpdateProcessor]:
        """Get the update processor for the main assistant graph."""
        from ee.hogai.factories.processor_factory import UpdateProcessorFactory

        return UpdateProcessorFactory.create_assistant_processor(self._team, self._user)

    async def _init_or_update_state(self) -> Optional[AssistantGraphState]:
        """Initialize or update the assistant state."""
        graph = self._create_graph()
        config = self._get_config()
        snapshot = await graph.aget_state(config)

        # If the graph previously hasn't reset the state, it is an interrupt. We resume from the point of interruption.
        if snapshot.next and self._latest_message:
            # The MigratingDjangoCheckpointer already handled migration when loading the checkpoint
            # so snapshot.values is always a dict that can be validated into the correct state type
            saved_state = AssistantGraphState.model_validate(snapshot.values)
            if saved_state.graph_status == "interrupted":
                self._state = saved_state
                await graph.aupdate_state(
                    config,
                    PartialAssistantGraphState(
                        messages=[self._latest_message], graph_status="resumed", query_generation_retry_count=0
                    ),
                )
                # Return None to indicate that we want to continue the execution from the interrupted point.
                return None

        # Append the new message and reset some fields to their default values.
        if self._latest_message:
            initial_state = AssistantGraphState(
                messages=[self._latest_message],
                start_id=self._latest_message.id,
                graph_status=None,
            )
        else:
            initial_state = AssistantGraphState(messages=[])

        self._state = initial_state
        return initial_state

    def _should_send_initial_message(self) -> bool:
        """Main assistant should send initial message."""
        return True

    def _create_interrupt_state(self, interrupt_messages: list[AssistantMessage]):
        """Create interrupt state for main assistant."""
        return PartialAssistantGraphState(
            messages=interrupt_messages,
            # LangGraph by some reason doesn't store the interrupt exceptions in checkpoints.
            graph_status="interrupted",
        )

    def _get_reset_state(self):
        """Get reset state for error recovery."""
        return PartialAssistantGraphState.get_reset_state()

    async def _report_conversation_state(
        self,
        last_assistant_message: AssistantMessage | None = None,
        last_visualization_message: VisualizationMessage | None = None,
    ):
        """Report conversation state for main assistant analytics."""
        if not self._user:
            return

        visualization_response = (
            last_visualization_message.model_dump_json(exclude_none=True) if last_visualization_message else None
        )
        output = last_assistant_message.content if isinstance(last_assistant_message, AssistantMessage) else None

        await database_sync_to_async(report_user_action)(
            self._user,
            "chat with ai",
            {
                "prompt": self._latest_message.content if self._latest_message else None,
                "output": output,
                "response": visualization_response,
            },
        )
