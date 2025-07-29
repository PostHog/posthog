import re
from typing import Literal, Union

from pydantic import BaseModel, field_validator
from ee.hogai.graph.taxonomy_toolkit import (
    TaxonomyAgentToolkit,
    retrieve_event_properties,
    retrieve_action_properties,
    retrieve_entity_properties,
    retrieve_event_property_values,
    retrieve_action_property_values,
    retrieve_entity_property_values,
    ask_user_for_help,
)
from posthog.models import Team

MaxSupportedQueryKind = Literal["trends", "funnel", "retention", "sql"]


class final_answer(BaseModel):
    """
    Use this tool to finalize the answer to the user's question.
    """

    query_kind: MaxSupportedQueryKind
    plan: str

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


TaxonomyAgentToolUnion = Union[
    retrieve_event_properties,
    retrieve_action_properties,
    retrieve_entity_properties,
    retrieve_event_property_values,
    retrieve_action_property_values,
    retrieve_entity_property_values,
    ask_user_for_help,
    final_answer,
]


class TaxonomyAgentTool(BaseModel):
    name: str
    arguments: TaxonomyAgentToolUnion


class QueryPlannerTaxonomyAgentToolkit(TaxonomyAgentToolkit[TaxonomyAgentTool, TaxonomyAgentTool]):
    def __init__(self, team: Team):
        super().__init__(team=team)

    # def _generate_properties_xml(self, children: list[tuple[str, str | None, str | None]]):
    #     root = ET.Element("properties")
    #     property_type_to_tag = {}

    #     for name, property_type, description in children:
    #         # Do not include properties that are ambiguous.
    #         if property_type is None:
    #             continue
    #         if property_type not in property_type_to_tag:
    #             property_type_to_tag[property_type] = ET.SubElement(root, property_type)

    #         type_tag = property_type_to_tag[property_type]
    #         prop = ET.SubElement(type_tag, "prop")
    #         ET.SubElement(prop, "name").text = name
    #         if description:
    #             ET.SubElement(prop, "description").text = description

    #     return ET.tostring(root, encoding="unicode")

    # def _generate_properties_output(self, props: list[tuple[str, str | None, str | None]]) -> str:
    #     """
    #     Generate the output format for properties. Can be overridden by subclasses.
    #     Default implementation uses XML format.
    #     """
    #     return self._generate_properties_xml(props)

    # def _retrieve_event_or_action_taxonomy(self, event_name_or_action_id: str | int):
    #     is_event = isinstance(event_name_or_action_id, str)
    #     if is_event:
    #         query = EventTaxonomyQuery(event=event_name_or_action_id, maxPropertyValues=25)
    #         verbose_name = f"event {event_name_or_action_id}"
    #     else:
    #         query = EventTaxonomyQuery(actionId=event_name_or_action_id, maxPropertyValues=25)
    #         verbose_name = f"action with ID {event_name_or_action_id}"
    #     runner = EventTaxonomyQueryRunner(query, self._team)
    #     response = runner.run(ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS)
    #     return response, verbose_name

    # def retrieve_event_or_action_property_values(self, event_name_or_action_id: str | int, property_name: str) -> str:
    #     try:
    #         property_definition = PropertyDefinition.objects.get(
    #             team=self._team, name=property_name, type=PropertyDefinition.Type.EVENT
    #         )
    #     except PropertyDefinition.DoesNotExist:
    #         return f"The property {property_name} does not exist in the taxonomy."

    #     response, verbose_name = self._retrieve_event_or_action_taxonomy(event_name_or_action_id)
    #     if not isinstance(response, CachedEventTaxonomyQueryResponse):
    #         return f"The {verbose_name} does not exist in the taxonomy."
    #     if not response.results:
    #         return f"Property values for {property_name} do not exist in the taxonomy for the {verbose_name}."

    #     prop = next((item for item in response.results if item.property == property_name), None)
    #     if not prop:
    #         return f"The property {property_name} does not exist in the taxonomy for the {verbose_name}."

    #     return self._format_property_values(
    #         prop.sample_values,
    #         prop.sample_count,
    #         format_as_string=property_definition.property_type in (PropertyType.String, PropertyType.Datetime),
    #     )

    # def _retrieve_session_properties(self, property_name: str) -> str:
    #     """
    #     Sessions properties example property values are hardcoded.
    #     """
    #     if property_name not in CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"]:
    #         return f"The property {property_name} does not exist in the taxonomy."

    #     sample_values: list[str | int | float]
    #     if property_name == "$channel_type":
    #         sample_values = cast(list[str | int | float], DEFAULT_CHANNEL_TYPES.copy())
    #         sample_count = len(sample_values)
    #         is_str = True
    #     elif (
    #         property_name in CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"]
    #         and "examples" in CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"][property_name]
    #     ):
    #         sample_values = CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"][property_name]["examples"]
    #         sample_count = None
    #         is_str = (
    #             CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"][property_name]["type"] == PropertyType.String
    #         )
    #     else:
    #         return f"Property values for {property_name} do not exist in the taxonomy for the session entity."

    #     return self._format_property_values(sample_values, sample_count, format_as_string=is_str)

    # def retrieve_entity_property_values(self, entity: str, property_name: str) -> str:
    #     if entity not in self._entity_names:
    #         return f"The entity {entity} does not exist in the taxonomy. You must use one of the following: {', '.join(self._entity_names)}."

    #     if entity == "session":
    #         return self._retrieve_session_properties(property_name)
    #     if entity == "person":
    #         query = ActorsPropertyTaxonomyQuery(property=property_name, maxPropertyValues=25)
    #     elif entity == "event":
    #         query = ActorsPropertyTaxonomyQuery(property=property_name, maxPropertyValues=50)
    #     else:
    #         group_index = next((group.group_type_index for group in self._groups if group.group_type == entity), None)
    #         if group_index is None:
    #             return f"The entity {entity} does not exist in the taxonomy."
    #         query = ActorsPropertyTaxonomyQuery(
    #             group_type_index=group_index, property=property_name, maxPropertyValues=25
    #         )

    #     try:
    #         if query.group_type_index is not None:
    #             prop_type = PropertyDefinition.Type.GROUP
    #             group_type_index = query.group_type_index
    #         elif entity == "event":
    #             prop_type = PropertyDefinition.Type.EVENT
    #             group_type_index = None
    #         else:
    #             prop_type = PropertyDefinition.Type.PERSON
    #             group_type_index = None
    #         property_definition = PropertyDefinition.objects.get(
    #             team=self._team,
    #             name=property_name,
    #             type=prop_type,
    #             group_type_index=group_type_index,
    #         )
    #     except PropertyDefinition.DoesNotExist:
    #         return f"The property {property_name} does not exist in the taxonomy for the entity {entity}."

    #     response = ActorsPropertyTaxonomyQueryRunner(query, self._team).run(
    #         ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS
    #     )

    #     if not isinstance(response, CachedActorsPropertyTaxonomyQueryResponse):
    #         return f"The entity {entity} does not exist in the taxonomy."

    #     if not response.results:
    #         return f"Property values for {property_name} do not exist in the taxonomy for the entity {entity}."

    #     return self._format_property_values(
    #         response.results.sample_values,
    #         response.results.sample_count,
    #         format_as_string=property_definition.property_type in (PropertyType.String, PropertyType.Datetime),
    #     )

    def get_tools(self) -> list:
        """Get tool signatures for query planning."""
        return [
            retrieve_event_properties,
            retrieve_action_properties,
            retrieve_entity_properties,
            retrieve_event_property_values,
            retrieve_action_property_values,
            retrieve_entity_property_values,
            ask_user_for_help,
            final_answer,
        ]

    def handle_tools(self, tool_name: str, tool_input: TaxonomyAgentTool) -> tuple[str, str]:
        """Handle tool execution and return (tool_id, result)."""
        if tool_name == "retrieve_event_properties":
            result = self.retrieve_event_or_action_properties(tool_input.arguments.event_name)  # type: ignore
        elif tool_name == "retrieve_action_properties":
            result = self.retrieve_event_or_action_properties(tool_input.arguments.action_id)  # type: ignore
        elif tool_name == "retrieve_entity_properties":
            result = self.retrieve_entity_properties(tool_input.arguments.entity)  # type: ignore
        elif tool_name == "retrieve_event_property_values":
            result = self.retrieve_event_or_action_property_values(
                tool_input.arguments.event_name,
                tool_input.arguments.property_name,  # type: ignore
            )
        elif tool_name == "retrieve_action_property_values":
            result = self.retrieve_event_or_action_property_values(
                tool_input.arguments.action_id,
                tool_input.arguments.property_name,  # type: ignore
            )
        elif tool_name == "retrieve_entity_property_values":
            result = self.retrieve_entity_property_values(
                tool_input.arguments.entity,
                tool_input.arguments.property_name,  # type: ignore
            )
        elif tool_name == "ask_user_for_help":
            result = tool_input.arguments.request  # type: ignore
        elif tool_name == "final_answer":
            result = "Query plan finalized"
        else:
            result = self.handle_incorrect_response(tool_input)

        return tool_name, result
