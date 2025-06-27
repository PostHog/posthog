import re
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from collections.abc import Iterable
from functools import cached_property
from textwrap import dedent
from typing import Literal, Optional, TypedDict, Union, cast

from pydantic import BaseModel, Field, RootModel, field_validator

from posthog.hogql.database.schema.channel_type import DEFAULT_CHANNEL_TYPES
from posthog.hogql_queries.ai.actors_property_taxonomy_query_runner import ActorsPropertyTaxonomyQueryRunner
from posthog.hogql_queries.ai.event_taxonomy_query_runner import EventTaxonomyQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Action, Team
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.property_definition import PropertyDefinition, PropertyType
from posthog.schema import (
    ActorsPropertyTaxonomyQuery,
    CachedActorsPropertyTaxonomyQueryResponse,
    CachedEventTaxonomyQueryResponse,
    EventTaxonomyQuery,
)
from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP


class ToolkitTool(TypedDict):
    name: str
    signature: str
    description: str


class RetrieveEntityPropertiesValuesArgs(BaseModel):
    entity: str
    property_name: str


class RetrieveEntityPropertiesValuesTool(BaseModel):
    name: Literal["retrieve_entity_property_values"]
    arguments: RetrieveEntityPropertiesValuesArgs


class RetrieveEventPropertiesValuesArgs(BaseModel):
    event_name: str
    property_name: str


class RetrieveEventPropertiesValuesTool(BaseModel):
    name: Literal["retrieve_event_property_values"]
    arguments: RetrieveEventPropertiesValuesArgs


class RetrieveActionPropertiesTool(BaseModel):
    name: Literal["retrieve_action_properties"]
    arguments: int


class RetrieveActionPropertiesValuesArgs(BaseModel):
    action_id: int
    property_name: str


class RetrieveActionPropertiesValuesTool(BaseModel):
    name: Literal["retrieve_action_property_values"]
    arguments: RetrieveActionPropertiesValuesArgs


class FinalAnswerTool(BaseModel):
    name: Literal["final_answer"]
    arguments: str

    @field_validator("arguments", mode="before")
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


class SingleArgumentTaxonomyAgentTool(BaseModel):
    name: Literal[
        "retrieve_entity_properties",
        "retrieve_event_properties",
        "handle_incorrect_response",
        "ask_user_for_help",
    ]
    arguments: str


TaxonomyAgentToolUnion = Union[
    SingleArgumentTaxonomyAgentTool,
    RetrieveEntityPropertiesValuesTool,
    RetrieveEventPropertiesValuesTool,
    RetrieveActionPropertiesTool,
    RetrieveActionPropertiesValuesTool,
    FinalAnswerTool,
]


class TaxonomyAgentTool(RootModel[TaxonomyAgentToolUnion]):
    root: TaxonomyAgentToolUnion = Field(..., discriminator="name")


class TaxonomyAgentToolkit(ABC):
    _team: Team

    def __init__(self, team: Team):
        self._team = team

    @cached_property
    def tools(self) -> list[ToolkitTool]:
        return [
            {
                "name": tool["name"],
                "signature": tool["signature"],
                "description": dedent(tool["description"]),
            }
            for tool in self._get_tools()
        ]

    @abstractmethod
    def _get_tools(self) -> list[ToolkitTool]:
        raise NotImplementedError

    @property
    def _default_tools(self) -> list[ToolkitTool]:
        stringified_entities = ", ".join([f"'{entity}'" for entity in self._entity_names])
        return [
            {
                "name": "retrieve_event_properties",
                "signature": "(event_name: str)",
                "description": """
                    Use this tool to retrieve the property names of an event. You will receive a list of properties containing their name, value type, and description, or a message that properties have not been found.

                    - **Try other events** if the tool doesn't return any properties.
                    - **Prioritize properties that are directly related to the context or objective of the user's query.**
                    - **Avoid using ambiguous properties** unless their relevance is explicitly confirmed.

                    Args:
                        event_name: The name of the event that you want to retrieve properties for.
                """,
            },
            {
                "name": "retrieve_event_property_values",
                "signature": "(event_name: str, property_name: str)",
                "description": """
                    Use this tool to retrieve the property values for an event. Adjust filters to these values. You will receive a list of property values or a message that property values have not been found. Some properties can have many values, so the output will be truncated. Use your judgment to find a proper value.

                    Args:
                        event_name: The name of the event that you want to retrieve values for.
                        property_name: The name of the property that you want to retrieve values for.
                """,
            },
            {
                "name": "retrieve_action_properties",
                "signature": "(action_id: int)",
                "description": """
                    Use this tool to retrieve the property names of an action. You will receive a list of properties containing their name, value type, and description, or a message that properties have not been found.

                    - **Try other actions or events** if the tool doesn't return any properties.
                    - **Prioritize properties that are directly related to the context or objective of the user's query.**
                    - **Avoid using ambiguous properties** unless their relevance is explicitly confirmed.

                    Args:
                        action_id: The ID of the action that you want to retrieve properties for.
                """,
            },
            {
                "name": "retrieve_action_property_values",
                "signature": "(action_id: int, property_name: str)",
                "description": """
                    Use this tool to retrieve the property values for an action. Adjust filters to these values. You will receive a list of property values or a message that property values have not been found. Some properties can have many values, so the output will be truncated. Use your judgment to find a proper value.

                    Args:
                        action_id: The ID of the action that you want to retrieve values for.
                        property_name: The name of the property that you want to retrieve values for.
                """,
            },
            {
                "name": f"retrieve_entity_properties",
                "signature": f"(entity: Literal[{stringified_entities}])",
                "description": """
                    Use this tool to retrieve property names for a property group (entity). You will receive a list of properties containing their name, value type, and description, or a message that properties have not been found.

                    - **Infer the property groups from the user's request.**
                    - **Try other entities** if the tool doesn't return any properties.
                    - **Prioritize properties that are directly related to the context or objective of the user's query.**
                    - **Avoid using ambiguous properties** unless their relevance is explicitly confirmed.

                    Args:
                        entity: The type of the entity that you want to retrieve properties for.
                """,
            },
            {
                "name": "retrieve_entity_property_values",
                "signature": f"(entity: Literal[{stringified_entities}], property_name: str)",
                "description": """
                    Use this tool to retrieve property values for a property name. Adjust filters to these values. You will receive a list of property values or a message that property values have not been found. Some properties can have many values, so the output will be truncated. Use your judgment to find a proper value.

                    Args:
                        entity: The type of the entity that you want to retrieve properties for.
                        property_name: The name of the property that you want to retrieve values for.
                """,
            },
            {
                "name": "ask_user_for_help",
                "signature": "(question: str)",
                "description": """
                    Use this tool to ask a question to the user. Your question must be concise and clear.

                    Args:
                        question: The question you want to ask.
                """,
            },
        ]

    def render_text_description(self) -> str:
        """
        Render the tool name and description in plain text.

        Returns:
            The rendered text.

        Output will be in the format of:

        .. code-block:: markdown

            search: This tool is used for search
            calculator: This tool is used for math
        """
        root = ET.Element("tools")
        for tool in self.tools:
            tool_tag = ET.SubElement(root, "tool")
            name_tag = ET.SubElement(tool_tag, "name")
            name_tag.text = f"{tool['name']}{tool['signature']}"
            description_tag = ET.SubElement(tool_tag, "description")
            description_tag.text = tool["description"]
        return ET.tostring(root, encoding="unicode")

    @property
    def _groups(self):
        return GroupTypeMapping.objects.filter(project_id=self._team.project_id).order_by("group_type_index")

    @cached_property
    def _entity_names(self) -> list[str]:
        """
        The schemas use `group_type_index` for groups complicating things for the agent. Instead, we use groups' names,
        so the generation step will handle their indexes. Tools would need to support multiple arguments, or we would need
        to create various tools for different group types. Since we don't use function calling here, we want to limit the
        number of tools because non-function calling models can't handle many tools.
        """
        entities = [
            "person",
            "session",
            *[group.group_type for group in self._groups],
        ]
        return entities

    def _generate_properties_xml(self, children: list[tuple[str, str | None, str | None]]):
        root = ET.Element("properties")
        property_type_to_tag = {}

        for name, property_type, description in children:
            # Do not include properties that are ambiguous.
            if property_type is None:
                continue
            if property_type not in property_type_to_tag:
                property_type_to_tag[property_type] = ET.SubElement(root, property_type)

            type_tag = property_type_to_tag[property_type]
            prop = ET.SubElement(type_tag, "prop")
            ET.SubElement(prop, "name").text = name
            if description:
                ET.SubElement(prop, "description").text = description

        return ET.tostring(root, encoding="unicode")

    def _enrich_props_with_descriptions(self, entity: str, props: Iterable[tuple[str, str | None]]):
        enriched_props = []
        mapping = {
            "session": CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"],
            "person": CORE_FILTER_DEFINITIONS_BY_GROUP["person_properties"],
            "event": CORE_FILTER_DEFINITIONS_BY_GROUP["event_properties"],
        }
        for prop_name, prop_type in props:
            description = None
            if entity_definition := mapping.get(entity, {}).get(prop_name):
                if entity_definition.get("system") or entity_definition.get("ignored_in_assistant"):
                    continue
                description = entity_definition.get("description_llm") or entity_definition.get("description")
            enriched_props.append((prop_name, prop_type, description))
        return enriched_props

    def retrieve_entity_properties(self, entity: str) -> str:
        """
        Retrieve properties for an entitiy like person, session, or one of the groups.
        """
        if entity not in ("person", "session", *[group.group_type for group in self._groups]):
            return f"Entity {entity} does not exist in the taxonomy."

        if entity == "person":
            qs = PropertyDefinition.objects.filter(team=self._team, type=PropertyDefinition.Type.PERSON).values_list(
                "name", "property_type"
            )
            props = self._enrich_props_with_descriptions("person", qs)
        elif entity == "session":
            # Session properties are not in the DB.
            props = self._enrich_props_with_descriptions(
                "session",
                [
                    (prop_name, prop["type"])
                    for prop_name, prop in CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"].items()
                    if prop.get("type") is not None
                ],
            )
        else:
            group_type_index = next(
                (group.group_type_index for group in self._groups if group.group_type == entity), None
            )
            if group_type_index is None:
                return f"Group {entity} does not exist in the taxonomy."
            qs = PropertyDefinition.objects.filter(
                team=self._team, type=PropertyDefinition.Type.GROUP, group_type_index=group_type_index
            ).values_list("name", "property_type")
            props = self._enrich_props_with_descriptions(entity, qs)

        if not props:
            return f"Properties do not exist in the taxonomy for the entity {entity}."

        return self._generate_properties_xml(props)

    def _retrieve_event_or_action_taxonomy(self, event_name_or_action_id: str | int):
        is_event = isinstance(event_name_or_action_id, str)
        if is_event:
            query = EventTaxonomyQuery(event=event_name_or_action_id, maxPropertyValues=25)
            verbose_name = f"event {event_name_or_action_id}"
        else:
            query = EventTaxonomyQuery(actionId=event_name_or_action_id, maxPropertyValues=25)
            verbose_name = f"action with ID {event_name_or_action_id}"
        runner = EventTaxonomyQueryRunner(query, self._team)
        response = runner.run(ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS)
        return response, verbose_name

    def retrieve_event_or_action_properties(self, event_name_or_action_id: str | int) -> str:
        """
        Retrieve properties for an event.
        """
        try:
            response, verbose_name = self._retrieve_event_or_action_taxonomy(event_name_or_action_id)
        except Action.DoesNotExist:
            project_actions = Action.objects.filter(team__project_id=self._team.project_id, deleted=False)
            if not project_actions:
                return "No actions exist in the project."
            return f"Action {event_name_or_action_id} does not exist in the taxonomy. Verify that the action ID is correct and try again."

        if not isinstance(response, CachedEventTaxonomyQueryResponse):
            return "Properties have not been found."
        if not response.results:
            return f"Properties do not exist in the taxonomy for the {verbose_name}."

        # Intersect properties with their types.
        qs = PropertyDefinition.objects.filter(
            team=self._team, type=PropertyDefinition.Type.EVENT, name__in=[item.property for item in response.results]
        )
        property_to_type = {property_definition.name: property_definition.property_type for property_definition in qs}
        props = [
            (item.property, property_to_type.get(item.property))
            for item in response.results
            # Exclude properties that exist in the taxonomy, but don't have a type.
            if item.property in property_to_type
        ]

        if not props:
            return f"Properties do not exist in the taxonomy for the {verbose_name}."

        return self._generate_properties_xml(self._enrich_props_with_descriptions("event", props))

    def _format_property_values(
        self, sample_values: list, sample_count: Optional[int] = 0, format_as_string: bool = False
    ) -> str:
        if len(sample_values) == 0 or sample_count == 0:
            return f"The property does not have any values in the taxonomy."

        # Add quotes to the String type, so the LLM can easily infer a type.
        # Strings like "true" or "10" are interpreted as booleans or numbers without quotes, so the schema generation fails.
        # Remove the floating point the value is an integer.
        formatted_sample_values: list[str] = []
        for value in sample_values:
            if format_as_string:
                formatted_sample_values.append(f'"{value}"')
            elif isinstance(value, float) and value.is_integer():
                formatted_sample_values.append(str(int(value)))
            else:
                formatted_sample_values.append(str(value))
        prop_values = ", ".join(formatted_sample_values)

        # If there wasn't an exact match with the user's search, we provide a hint that LLM can use an arbitrary value.
        if sample_count is None:
            return f"{prop_values} and many more distinct values."
        elif sample_count > len(sample_values):
            diff = sample_count - len(sample_values)
            return f"{prop_values} and {diff} more distinct value{'' if diff == 1 else 's'}."

        return prop_values

    def retrieve_event_or_action_property_values(self, event_name_or_action_id: str | int, property_name: str) -> str:
        try:
            property_definition = PropertyDefinition.objects.get(
                team=self._team, name=property_name, type=PropertyDefinition.Type.EVENT
            )
        except PropertyDefinition.DoesNotExist:
            return f"The property {property_name} does not exist in the taxonomy."

        response, verbose_name = self._retrieve_event_or_action_taxonomy(event_name_or_action_id)
        if not isinstance(response, CachedEventTaxonomyQueryResponse):
            return f"The {verbose_name} does not exist in the taxonomy."
        if not response.results:
            return f"Property values for {property_name} do not exist in the taxonomy for the {verbose_name}."

        prop = next((item for item in response.results if item.property == property_name), None)
        if not prop:
            return f"The property {property_name} does not exist in the taxonomy for the {verbose_name}."

        return self._format_property_values(
            prop.sample_values,
            prop.sample_count,
            format_as_string=property_definition.property_type in (PropertyType.String, PropertyType.Datetime),
        )

    def _retrieve_session_properties(self, property_name: str) -> str:
        """
        Sessions properties example property values are hardcoded.
        """
        if property_name not in CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"]:
            return f"The property {property_name} does not exist in the taxonomy."

        sample_values: list[str | int | float]
        if property_name == "$channel_type":
            sample_values = cast(list[str | int | float], DEFAULT_CHANNEL_TYPES.copy())
            sample_count = len(sample_values)
            is_str = True
        elif (
            property_name in CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"]
            and "examples" in CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"][property_name]
        ):
            sample_values = CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"][property_name]["examples"]
            sample_count = None
            is_str = (
                CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"][property_name]["type"] == PropertyType.String
            )
        else:
            return f"Property values for {property_name} do not exist in the taxonomy for the session entity."

        return self._format_property_values(sample_values, sample_count, format_as_string=is_str)

    def retrieve_entity_property_values(self, entity: str, property_name: str) -> str:
        if entity not in self._entity_names:
            return f"The entity {entity} does not exist in the taxonomy. You must use one of the following: {', '.join(self._entity_names)}."

        if entity == "session":
            return self._retrieve_session_properties(property_name)

        if entity == "person":
            query = ActorsPropertyTaxonomyQuery(property=property_name, maxPropertyValues=25)
        else:
            group_index = next((group.group_type_index for group in self._groups if group.group_type == entity), None)
            if group_index is None:
                return f"The entity {entity} does not exist in the taxonomy."
            query = ActorsPropertyTaxonomyQuery(
                group_type_index=group_index, property=property_name, maxPropertyValues=25
            )

        try:
            if query.group_type_index is not None:
                prop_type = PropertyDefinition.Type.GROUP
                group_type_index = query.group_type_index
            else:
                prop_type = PropertyDefinition.Type.PERSON
                group_type_index = None

            property_definition = PropertyDefinition.objects.get(
                team=self._team,
                name=property_name,
                type=prop_type,
                group_type_index=group_type_index,
            )
        except PropertyDefinition.DoesNotExist:
            return f"The property {property_name} does not exist in the taxonomy for the entity {entity}."

        response = ActorsPropertyTaxonomyQueryRunner(query, self._team).run(
            ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS
        )

        if not isinstance(response, CachedActorsPropertyTaxonomyQueryResponse):
            return f"The entity {entity} does not exist in the taxonomy."

        if not response.results:
            return f"Property values for {property_name} do not exist in the taxonomy for the entity {entity}."

        return self._format_property_values(
            response.results.sample_values,
            response.results.sample_count,
            format_as_string=property_definition.property_type in (PropertyType.String, PropertyType.Datetime),
        )

    def handle_incorrect_response(self, response: str) -> str:
        """
        No-op tool. Take a parsing error and return a response that the LLM can use to correct itself.
        Used to control a number of retries.
        """
        return response
