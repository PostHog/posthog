from enum import Enum
from functools import cached_property
from typing import Union, Literal
from pydantic import BaseModel, ConfigDict, Field, RootModel
from ee.hogai.graph.taxonomy_agent.toolkit import TaxonomyAgentToolkit, ToolkitTool, RetrieveEntityPropertiesValuesTool


class EntityType(str, Enum):
    """Base entity types for filtering."""

    PERSON = "person"
    SESSION = "session"
    EVENT = "event"

    @classmethod
    def values(cls) -> list[str]:
        """Get all entity type values as strings."""
        return [entity.value for entity in cls]


class RetrieveEntityPropertiesToolArgs(BaseModel):
    entity: str = Field(..., description="The entity type (e.g. 'person', 'session', 'event')")


class RetrieveEntityPropertiesTool(BaseModel):
    """
    Retrieves available property names for a specific entity type (e.g., events, users, groups).
    Use when you know the entity type but need to discover what properties are available.
    Returns property names, data types, and descriptions.
    """

    model_config = ConfigDict(title="retrieve_entity_properties")

    name: Literal["retrieve_entity_properties"]
    arguments: RetrieveEntityPropertiesToolArgs


class AskUserForHelpToolArgs(BaseModel):
    request: str = Field(..., description="The question you want to ask the user.")


class AskUserForHelpTool(BaseModel):
    """
    Use this tool to ask a clarifying question to the user. Your question must be concise and clear.
    """

    model_config = ConfigDict(title="ask_user_for_help")

    name: Literal["ask_user_for_help"]
    arguments: AskUserForHelpToolArgs


class FinalAnswerToolArgs(BaseModel):
    """
    Use this tool to finalize the filter options answer.
    You MUST use this tool ONLY when you have all the information you need to build the filter.
    If you don't have all the information you need, use the `ask_user_for_help` tool to ask the user for clarification.
    """

    result: str = Field(description="Should be 'filter' for filter responses.")
    data: dict = Field(description="Complete filter object as defined in the prompts")


class FinalAnswerTool(BaseModel):
    """Tool for providing the final answer with filter data."""

    model_config = ConfigDict(title="final_answer")

    name: Literal["final_answer"]
    arguments: FinalAnswerToolArgs


FilterOptionsToolUnion = Union[
    RetrieveEntityPropertiesTool,
    RetrieveEntityPropertiesValuesTool,
    AskUserForHelpTool,
    FinalAnswerTool,
]


class FilterOptionsTool(RootModel[FilterOptionsToolUnion]):
    root: FilterOptionsToolUnion = Field(..., discriminator="name")


class FilterOptionsToolkit(TaxonomyAgentToolkit):
    def _get_tools(self) -> list[ToolkitTool]:
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

    # def retrieve_entity_properties(self, entity: str) -> str:
    #     """
    #     Use parent implementation but with custom error messages for better UX.
    #     """
    #     if entity not in self._entity_names:
    #         return f"Entity '{entity}' does not exist. Available entities are: {', '.join(self._entity_names)}. Try one of these other entities."

    #     # Use parent implementation
    #     result = super().retrieve_entity_properties(entity)

    #     # if "does not exist in the taxonomy" in result and entity in result:
    #     #     if "Group" in result:
    #     #         return f"Group {entity} does not exist in the taxonomy. Try one of these other groups: {', '.join([group.group_type for group in self._groups])}."
    #     #     elif "Properties do not exist" in result:
    #     #         return f"Properties do not exist in the taxonomy for the entity {entity}. Try one of these other entities: {', '.join(self._entity_names)}."

    #     return result

    # def retrieve_entity_property_values(self, entity: str, property_name: str) -> str:
    #     """
    #     Override parent implementation with different logic for session properties and error messages.
    #     """

    #     if entity not in self._entity_names:
    #         return f"The entity {entity} does not exist in the taxonomy. Try one of these entities: {', '.join(self._entity_names)}."

    #     if entity == "person" or entity == "session":
    #         query = ActorsPropertyTaxonomyQuery(property=property_name, maxPropertyValues=MAX_PROP_VALUES)
    #     else:
    #         group_index = next((group.group_type_index for group in self._groups if group.group_type == entity), None)
    #         if group_index is None:
    #             return f"The entity {entity} does not exist in the taxonomy."
    #         query = ActorsPropertyTaxonomyQuery(
    #             group_type_index=group_index, property=property_name, maxPropertyValues=MAX_PROP_VALUES
    #         )

    #     try:
    #         if query.group_type_index is not None:
    #             prop_type = PropertyDefinition.Type.GROUP
    #             group_type_index = query.group_type_index
    #         elif entity == "person":
    #             prop_type = PropertyDefinition.Type.PERSON
    #             group_type_index = None
    #         elif entity == "session":
    #             prop_type = PropertyDefinition.Type.SESSION
    #             group_type_index = None

    #         property_definition = PropertyDefinition.objects.get(
    #             team=self._team,
    #             name=property_name,
    #             type=prop_type,
    #             group_type_index=group_type_index,
    #         )
    #     except PropertyDefinition.DoesNotExist:
    #         return f"The property {property_name} does not exist in the taxonomy for the entity {entity}. Try another property that is relevant to the user's question."

    #     response = ActorsPropertyTaxonomyQueryRunner(query, self._team).run(
    #         ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS
    #     )

    #     if not isinstance(response, CachedActorsPropertyTaxonomyQueryResponse):
    #         return f"The entity {entity} does not exist in the taxonomy."

    #     if not response.results:
    #         return f"Property values for {property_name} do not exist in the taxonomy for the entity {entity}. Use the value that the user has provided in the query."

    #     return self._format_property_values(
    #         response.results.sample_values,
    #         response.results.sample_count,
    #         format_as_string=property_definition.property_type in (PropertyType.String, PropertyType.Datetime),
    #     )

    def handle_incorrect_response(self, response: BaseModel) -> str:
        """
        Override parent implementation to handle BaseModel responses.
        """
        return response.model_dump_json()
