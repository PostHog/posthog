"""
Update processor for the Insights Assistant Graph.

Handles reasoning messages and update processing specific to insights generation.
"""

from typing import Optional

from ee.hogai.processors.update_processor import BaseGraphUpdateProcessor
from ee.hogai.states.graph_states import InsightsGraphState
from ee.hogai.utils.types import AssistantNodeName
from ee.hogai.graph.filter_options.types import FilterOptionsNodeName
from posthog.schema import ReasoningMessage
from posthog.models import Action


class InsightsUpdateProcessor(BaseGraphUpdateProcessor[InsightsGraphState]):
    """Processes updates for the insights graph."""

    @property
    def visualization_nodes(self):
        """Nodes that generate visualizations."""
        return {
            AssistantNodeName.TRENDS_GENERATOR,
            AssistantNodeName.FUNNEL_GENERATOR,
            AssistantNodeName.RETENTION_GENERATOR,
            AssistantNodeName.SQL_GENERATOR,
            AssistantNodeName.QUERY_EXECUTOR,
        }

    async def get_reasoning_message(
        self, node_name: AssistantNodeName | FilterOptionsNodeName, state: InsightsGraphState
    ) -> Optional[ReasoningMessage]:
        """Generate reasoning messages for insights graph nodes."""

        match node_name:
            case AssistantNodeName.QUERY_PLANNER | FilterOptionsNodeName.FILTER_OPTIONS:
                return await self._get_query_planner_reasoning(state)
            case AssistantNodeName.TRENDS_GENERATOR:
                return ReasoningMessage(content="Creating trends query")
            case AssistantNodeName.FUNNEL_GENERATOR:
                return ReasoningMessage(content="Creating funnel query")
            case AssistantNodeName.RETENTION_GENERATOR:
                return ReasoningMessage(content="Creating retention query")
            case AssistantNodeName.SQL_GENERATOR:
                return ReasoningMessage(content="Creating SQL query")
            case AssistantNodeName.QUERY_EXECUTOR:
                return ReasoningMessage(content="Running query")
            case AssistantNodeName.INSIGHT_RAG_CONTEXT:
                return ReasoningMessage(content="Gathering context")
            case _:
                return None

    async def _get_query_planner_reasoning(self, state: InsightsGraphState) -> ReasoningMessage:
        """Generate reasoning for query planner nodes."""
        substeps: list[str] = []

        if state and state.intermediate_steps:
            for action, _ in state.intermediate_steps:
                if isinstance(action.tool_input, dict):
                    match action.tool:
                        case "retrieve_event_properties":
                            substeps.append(f"Exploring `{action.tool_input['event_name']}` event's properties")
                        case "retrieve_entity_properties":
                            substeps.append(f"Exploring {action.tool_input['entity']} properties")
                        case "retrieve_event_property_values":
                            substeps.append(
                                f"Analyzing `{action.tool_input['event_name']}` event's "
                                f"property `{action.tool_input['property_name']}`"
                            )
                        case "retrieve_entity_property_values":
                            substeps.append(
                                f"Analyzing {action.tool_input['entity']} "
                                f"property `{action.tool_input['property_name']}`"
                            )
                        case "retrieve_action_properties" | "retrieve_action_property_values":
                            await self._add_action_substep(action, substeps)

        return ReasoningMessage(content="Picking relevant events and properties", substeps=substeps)

    async def _add_action_substep(self, action, substeps: list[str]) -> None:
        """Add substep for action-related tools."""
        try:
            action_model = await Action.objects.aget(
                pk=action.tool_input["action_id"], team__project_id=self._team.project_id
            )
            if action.tool == "retrieve_action_properties":
                substeps.append(f"Exploring `{action_model.name}` action properties")
            elif action.tool == "retrieve_action_property_values":
                substeps.append(
                    f"Analyzing `{action.tool_input['property_name']}` " f"action property of `{action_model.name}`"
                )
        except Action.DoesNotExist:
            pass
