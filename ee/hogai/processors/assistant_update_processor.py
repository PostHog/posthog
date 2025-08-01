"""
Update processor for the Main Assistant Graph.

Handles reasoning messages and update processing specific to the root assistant.
"""

from typing import Optional

from ee.hogai.processors.update_processor import BaseGraphUpdateProcessor
from ee.hogai.states.graph_states import AssistantGraphState
from ee.hogai.utils.types import AssistantNodeName
from ee.hogai.graph.filter_options.types import FilterOptionsNodeName
from ee.hogai.tool import CONTEXTUAL_TOOL_NAME_TO_TOOL
from ee.hogai.utils.helpers import find_last_ui_context
from posthog.schema import ReasoningMessage, AssistantMessage


class AssistantUpdateProcessor(BaseGraphUpdateProcessor[AssistantGraphState]):
    """Processes updates for the main assistant graph."""

    @property
    def verbose_nodes(self):
        """Nodes that can send messages to the client."""
        return {
            AssistantNodeName.ROOT,
            AssistantNodeName.INKEEP_DOCS,
            AssistantNodeName.MEMORY_ONBOARDING,
            AssistantNodeName.MEMORY_INITIALIZER,
            AssistantNodeName.MEMORY_ONBOARDING_ENQUIRY,
            AssistantNodeName.MEMORY_ONBOARDING_FINALIZE,
            AssistantNodeName.MEMORY_INITIALIZER_INTERRUPT,
            AssistantNodeName.ROOT_TOOLS,
        }

    @property
    def streaming_nodes(self):
        """Nodes that can stream messages to the client."""
        return {
            AssistantNodeName.ROOT,
            AssistantNodeName.INKEEP_DOCS,
            AssistantNodeName.MEMORY_ONBOARDING,
            AssistantNodeName.MEMORY_INITIALIZER,
            AssistantNodeName.MEMORY_ONBOARDING_ENQUIRY,
            AssistantNodeName.MEMORY_ONBOARDING_FINALIZE,
        }

    async def get_reasoning_message(
        self, node_name: AssistantNodeName | FilterOptionsNodeName, state: AssistantGraphState
    ) -> Optional[ReasoningMessage]:
        """Generate reasoning messages for assistant graph nodes."""

        match node_name:
            case AssistantNodeName.ROOT_TOOLS:
                return self._get_root_tools_reasoning(state)
            case AssistantNodeName.ROOT:
                return self._get_root_reasoning(state)
            case AssistantNodeName.MEMORY_INITIALIZER:
                return ReasoningMessage(content="Setting up conversation context")
            case AssistantNodeName.MEMORY_ONBOARDING:
                return ReasoningMessage(content="Understanding your needs")
            case AssistantNodeName.MEMORY_ONBOARDING_ENQUIRY:
                return ReasoningMessage(content="Gathering more information")
            case AssistantNodeName.BILLING:
                return ReasoningMessage(content="Checking your billing information")
            case AssistantNodeName.INKEEP_DOCS:
                return ReasoningMessage(content="Searching documentation")
            case AssistantNodeName.INSIGHTS_SEARCH:
                return ReasoningMessage(content="Searching for insights")
            case _:
                return None

    def _get_root_tools_reasoning(self, state: AssistantGraphState) -> Optional[ReasoningMessage]:
        """Generate reasoning for root tools node."""
        if not state.messages:
            return None

        last_message = state.messages[-1]
        if not isinstance(last_message, AssistantMessage):
            return None

        tool_calls = last_message.tool_calls or []
        if len(tool_calls) == 0:
            return None

        tool_call = tool_calls[0]

        match tool_call.name:
            case "create_and_query_insight":
                return ReasoningMessage(content="Coming up with an insight")
            case "search_documentation":
                return ReasoningMessage(content="Checking PostHog docs")
            case "retrieve_billing_information":
                return ReasoningMessage(content="Checking your billing data")
            case _:
                # Check contextual tools
                ToolClass = CONTEXTUAL_TOOL_NAME_TO_TOOL.get(tool_call.name)
                if ToolClass:
                    return ReasoningMessage(content=ToolClass(team=self._team, user=self._user).thinking_message)
                return ReasoningMessage(content=f"Running tool {tool_call.name}")

    def _get_root_reasoning(self, state: AssistantGraphState) -> Optional[ReasoningMessage]:
        """Generate reasoning for root node."""
        ui_context = find_last_ui_context(state.messages)
        if ui_context and (ui_context.dashboards or ui_context.insights):
            return ReasoningMessage(content="Calculating context")
        return None
