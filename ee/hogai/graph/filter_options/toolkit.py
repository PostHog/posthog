from enum import Enum
from functools import cached_property
from typing import Union
from pydantic import BaseModel, Field
from ee.hogai.graph.query_planner.toolkit import (
    TaxonomyAgentToolkit,
    retrieve_entity_properties,
    retrieve_entity_property_values,
    retrieve_event_properties,
    retrieve_event_property_values,
)
from posthog.schema import MaxRecordingUniversalFilters
import yaml


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


class ask_user_for_help(BaseModel):
    """
    Use this tool to ask a clarifying question to the user. Your question must be concise and clear.
    """

    request: str = Field(..., description="The question you want to ask the user.")


class final_answer(BaseModel):
    """
    Use this tool to finalize the filter options answer.
    You MUST use this tool ONLY when you have all the information you need to build the filter.
    If you don't have all the information you need, use the `ask_user_for_help` tool to ask the user for clarification.
    """

    data: MaxRecordingUniversalFilters = Field(description="Complete filter object as defined in the prompts")


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


class FilterOptionsToolkit(TaxonomyAgentToolkit):
    @cached_property
    def _entity_names(self) -> list[str]:
        """Override to use only actual entity types, not events."""
        return super()._entity_names

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

    def retrieve_entity_properties(self, entity: str, max_properties: int = 500) -> str:
        """
        Retrieve properties for an entity like person, session, or one of the groups.
        Events should use retrieve_event_properties instead.
        """
        if entity not in self._entity_names:
            return f"Entity '{entity}' does not exist. Available entities are: {', '.join(self._entity_names)}. Try one of these other entities."

        return super().retrieve_entity_properties(entity)

    def handle_incorrect_response(self, response: BaseModel) -> str:
        """
        Override parent implementation to handle BaseModel responses.
        """
        return response.model_dump_json()
