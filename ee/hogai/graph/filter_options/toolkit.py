from enum import Enum
from typing import Union, TypeVar
from pydantic import BaseModel, Field
from posthog.schema import MaxRecordingUniversalFilters
import yaml
from ee.hogai.graph.taxonomy import (
    TaxonomyAgentToolkit,
    retrieve_entity_properties,
    retrieve_entity_property_values,
    retrieve_event_properties,
    retrieve_event_property_values,
    ask_user_for_help,
)


class EntityType(str, Enum):
    """Base entity types for filtering."""

    PERSON = "person"
    SESSION = "session"
    EVENT = "event"
    ACTION = "action"

    @classmethod
    def values(cls) -> list[str]:
        """Get all entity type values as strings."""
        return [entity.value for entity in cls]


# Type variable for filter response types
T = TypeVar("T", bound=BaseModel)


def create_final_answer_model(response_model: type[T]) -> type[BaseModel]:
    """
    Create a dynamic final_answer model based on the response model from FilterProfile.
    """

    class final_answer(BaseModel):
        """
        Use this tool to finalize the filter options answer.
        You MUST use this tool ONLY when you have all the information you need to build the filter.
        If you don't have all the information you need, use the `ask_user_for_help` tool to ask the user for clarification.
        """

        data: response_model = Field(description="Complete filter object as defined in the prompts")

    return final_answer


# Default final_answer for backward compatibility
final_answer = create_final_answer_model(MaxRecordingUniversalFilters)


FilterOptionsToolUnion = Union[
    retrieve_entity_properties,
    retrieve_entity_property_values,
    ask_user_for_help,
    final_answer,
    retrieve_event_properties,
    retrieve_event_property_values,
]


class FilterOptionsTool(BaseModel):
    name: str
    arguments: FilterOptionsToolUnion


class FilterOptionsToolkit(TaxonomyAgentToolkit[FilterOptionsTool]):
    def __init__(self, team):
        super().__init__(team=team)
        self.output_schema_class = MaxRecordingUniversalFilters

    def get_tools(self) -> list:
        """Get all available tools for filter options."""
        # Create dynamic final_answer tool based on output schema
        dynamic_final_answer = create_final_answer_model(self.output_schema_class)

        return [
            retrieve_entity_properties,
            retrieve_entity_property_values,
            retrieve_event_properties,
            retrieve_event_property_values,
            ask_user_for_help,
            dynamic_final_answer,
        ]

    def handle_tools(self, tool_name: str, tool_input: FilterOptionsTool) -> tuple[str, str]:
        """Handle tool execution and return (tool_id, result)."""

        if tool_name == "retrieve_entity_property_values":
            result = self.retrieve_entity_property_values(
                tool_input.arguments.entity, tool_input.arguments.property_name
            )  # type: ignore
        elif tool_name == "retrieve_entity_properties":
            result = self.retrieve_entity_properties(tool_input.arguments.entity)  # type: ignore
        elif tool_name == "retrieve_event_property_values":
            result = self.retrieve_event_or_action_property_values(
                tool_input.arguments.event_name,  # type: ignore
                tool_input.arguments.property_name,  # type: ignore
            )
        elif tool_name == "retrieve_event_properties":
            result = self.retrieve_event_or_action_properties(tool_input.arguments.event_name)  # type: ignore
        elif tool_name == "ask_user_for_help":
            result = tool_input.arguments.request  # type: ignore
        elif tool_name == "final_answer":
            result = "Filter options finalized"
        else:
            result = self.handle_incorrect_response(tool_input)

        return tool_name, result

    def _generate_properties_output(self, props: list[tuple[str, str | None, str | None]]) -> str:
        """
        Override parent implementation to use YAML format instead of XML.
        """
        return self._generate_properties_yaml(props)

    def _generate_properties_yaml(self, children: list[tuple[str, str | None, str | None]]):
        properties_by_type = {}

        for name, property_type, description in children:
            # Do not include properties that are ambiguous.
            if property_type is None:
                continue

            if property_type not in properties_by_type:
                properties_by_type[property_type] = []

            prop_dict = {"name": name}
            if description:
                prop_dict["description"] = description

            properties_by_type[property_type].append(prop_dict)

        result = {"properties": properties_by_type}
        return yaml.dump(result, default_flow_style=False, sort_keys=True)
