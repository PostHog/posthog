from enum import Enum
from functools import cached_property
from typing import Union
from pydantic import BaseModel, Field
from ee.hogai.graph.query_planner.toolkit import (
    TaxonomyAgentToolkit,
    retrieve_entity_properties,
    retrieve_entity_property_values,
)
from posthog.models.property_definition import PropertyDefinition


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

    result: str = Field(description="Should be 'filter' for filter responses.")
    data: dict = Field(description="Complete filter object as defined in the prompts")


FilterOptionsToolUnion = Union[
    retrieve_entity_properties, retrieve_entity_property_values, ask_user_for_help, final_answer
]


class FilterOptionsTool(BaseModel):
    name: str
    arguments: FilterOptionsToolUnion


class FilterOptionsToolkit(TaxonomyAgentToolkit):
    def _get_tools(self) -> list[dict]:
        """Required implementation of abstract method from TaxonomyAgentToolkit"""
        stringified_entities = ", ".join([f"'{entity}'" for entity in self._entity_names])
        return [
            {
                "name": "retrieve_entity_properties",
                "signature": f"(entity: Literal[{stringified_entities}])",
                "description": """
                    Retrieves available property names for a specific entity type (e.g., events, users, groups).
                    Use when you know the entity type but need to discover what properties are available.
                    Returns property names, data types, and descriptions.

                    Args:
                        entity: The entity type (e.g. 'person', 'session', 'event')
                """,
            },
            {
                "name": "retrieve_entity_property_values",
                "signature": f"(entity: Literal[{stringified_entities}], property_name: str)",
                "description": """
                    Retrieves possible values for a specific property of a given entity type.
                    Use when you know both the entity type and property name but need to see available values.
                    Returns a list of actual property values found in the data or a message that values have not been found.

                    Args:
                        entity: The entity type (e.g. 'person', 'session', 'event')
                        property_name: Property name to retrieve values for.
                """,
            },
            {
                "name": "ask_user_for_help",
                "signature": "(request: str)",
                "description": """
                    Use this tool to ask a clarifying question to the user. Your question must be concise and clear.

                    Args:
                        request: The question you want to ask the user.
                """,
            },
            {
                "name": "final_answer",
                "signature": "(result: str, data: dict)",
                "description": """
                    Use this tool to finalize the filter options answer.
                    You MUST use this tool ONLY when you have all the information you need to build the filter.

                    Args:
                        result: Should be 'filter' for filter responses.
                        data: Complete filter object as defined in the prompts
                """,
            },
        ]

    @cached_property
    def _entity_names(self) -> list[str]:
        """
        Override to include event type and use EntityType enum.
        """
        return EntityType.values() + [group.group_type for group in self._groups]

    def _generate_properties_output(self, props: list[tuple[str, str | None, str | None]]) -> str:
        """
        Override parent implementation to use YAML format instead of XML.
        """
        return self._generate_properties_yaml(props)

    def _generate_properties_yaml(self, children: list[tuple[str, str | None, str | None]]):
        import yaml

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
        Retrieve properties for an entitiy like person, session, or one of the groups.
        """
        if entity not in self._entity_names:
            return f"Entity '{entity}' does not exist. Available entities are: {', '.join(self._entity_names)}. Try one of these other entities."

        if entity == EntityType.EVENT.value or entity == EntityType.ACTION.value:
            qs = PropertyDefinition.objects.filter(team=self._team, type=PropertyDefinition.Type.EVENT).values_list(
                "name", "property_type"
            )[:max_properties]
            props = self._enrich_props_with_descriptions("event", qs)
            if not props:
                return f"Properties do not exist in the taxonomy for the entity {entity}. Try one of these other entities: {', '.join(self._entity_names)}."

            return self._generate_properties_output(props)
        else:
            result = super().retrieve_entity_properties(entity)

        return result

    def handle_incorrect_response(self, response: BaseModel) -> str:
        """
        Override parent implementation to handle BaseModel responses.
        """
        return response.model_dump_json()
