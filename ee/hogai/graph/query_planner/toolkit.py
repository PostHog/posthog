import re
from typing import Literal

from ee.hogai.graph.taxonomy.toolkit import TaxonomyAgentToolkit, TaxonomyToolNotFoundError
from ee.hogai.graph.taxonomy.tools import retrieve_action_properties, retrieve_action_property_values
from pydantic import BaseModel, field_validator

from ee.hogai.graph.taxonomy.tools import get_dynamic_entity_tools
from posthog.models import Team

MaxSupportedQueryKind = Literal["trends", "funnel", "retention", "sql"]


class final_answer(BaseModel):
    """
    Use this tool to finalize the answer to the user's question.
    """

    plan: str
    query_kind: MaxSupportedQueryKind  # query_kind is intentionally AFTER plan so that these tokens are generated after decision explanation

    @field_validator("plan", mode="before")
    def normalize_plan(cls, plan: str) -> str:
        """
        Normalize the generated plan, so the `action` entity becomes `event`.
        """
        return re.sub(
            r"-\s*(entity:)?\s*action(?!\s*id)",
            "- entity: event",
            plan,
            flags=re.IGNORECASE | re.MULTILINE,
        )


class QueryPlannerTaxonomyAgentToolkit(TaxonomyAgentToolkit):
    def __init__(self, team: Team):
        super().__init__(team=team)

    def get_tools(self) -> list:
        """Get tool signatures for query planning."""
        dynamic_retrieve_entity_properties, dynamic_retrieve_entity_property_values = get_dynamic_entity_tools(
            self._team_group_types
        )
        return [
            *self._get_default_tools(),
            retrieve_action_properties,
            retrieve_action_property_values,
            final_answer,
            dynamic_retrieve_entity_properties,
            dynamic_retrieve_entity_property_values,
        ]

    def handle_tools(self, tool_name: str, tool_input: BaseModel) -> tuple[str, str]:
        """Handle tool execution and return (tool_id, result)."""
        try:
            tool_name, result = super().handle_tools(tool_name, tool_input)
        except TaxonomyToolNotFoundError:
            # We come here if the tool is not available in the taxonomy toolkit.
            # Must be a custom tool
            if tool_name == "retrieve_action_properties":
                result = self.retrieve_event_or_action_properties(tool_input.arguments.action_id)  # type: ignore
            elif tool_name == "retrieve_action_property_values":
                result = self.retrieve_event_or_action_property_values(
                    tool_input.arguments.action_id,  # type: ignore
                    tool_input.arguments.property_name,  # type: ignore
                )
            else:
                result = self.handle_incorrect_response(tool_input)

        return tool_name, result
