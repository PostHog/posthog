import json
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from functools import cached_property
from textwrap import dedent
from typing import Any, Literal, Optional, TypedDict, Union

from pydantic import BaseModel, Field, RootModel

from ee.hogai.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP
from posthog.hogql.database.schema.channel_type import POSSIBLE_CHANNEL_TYPES
from posthog.hogql_queries.ai.actors_property_taxonomy_query_runner import ActorsPropertyTaxonomyQueryRunner
from posthog.hogql_queries.ai.event_taxonomy_query_runner import EventTaxonomyQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.property_definition import PropertyDefinition, PropertyType
from posthog.models.team.team import Team
from posthog.schema import (
    ActorsPropertyTaxonomyQuery,
    CachedActorsPropertyTaxonomyQueryResponse,
    CachedEventTaxonomyQueryResponse,
    EventTaxonomyQuery,
    ExperimentalAITrendsQuery,
)


class ToolkitTool(TypedDict):
    name: str
    signature: str
    description: str


class RetrieveEntityPropertiesValuesArgsModel(BaseModel):
    entity: str
    property_name: str


class RetrieveEntityPropertiesValuesModel(BaseModel):
    name: Literal["retrieve_entity_property_values"]
    arguments: RetrieveEntityPropertiesValuesArgsModel


class RetrieveEventPropertiesValuesArgsModel(BaseModel):
    event_name: str
    property_name: str


class RetrieveEventPropertiesValuesModel(BaseModel):
    name: Literal["retrieve_event_property_values"]
    arguments: RetrieveEventPropertiesValuesArgsModel


class SingleArgumentTrendsAgentToolModel(BaseModel):
    name: Literal[
        "retrieve_entity_properties",
        "retrieve_event_properties",
        "final_answer",
        "handle_incorrect_response",
    ]
    arguments: str


class TrendsAgentToolModel(
    RootModel[
        Union[
            SingleArgumentTrendsAgentToolModel, RetrieveEntityPropertiesValuesModel, RetrieveEventPropertiesValuesModel
        ]
    ]
):
    root: Union[
        SingleArgumentTrendsAgentToolModel, RetrieveEntityPropertiesValuesModel, RetrieveEventPropertiesValuesModel
    ] = Field(..., discriminator="name")


class TrendsAgentToolkit:
    _team: Team

    def __init__(self, team: Team):
        self._team = team

    @property
    def groups(self):
        return GroupTypeMapping.objects.filter(team=self._team).order_by("group_type_index")

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
            *[group.group_type for group in self.groups],
        ]
        return entities

    @cached_property
    def tools(self) -> list[ToolkitTool]:
        """
        Our ReAct agent doesn't use function calling. Instead, it uses tools in natural language to decide next steps. The agent expects the following format:

        ```
        retrieve_entity_properties_tool(entity: "Literal['person', 'session', 'organization', 'instance', 'project']") - description.
        ```

        Events and other entities are intentionally separated for properties retrieval. Potentially, there can be different functions for each entity type.
        """

        stringified_entities = ", ".join([f"'{entity}'" for entity in self._entity_names])

        tools: list[ToolkitTool] = [
            {
                "name": tool["name"],
                "signature": tool["signature"],
                "description": dedent(tool["description"]),
            }
            for tool in [
                {
                    "name": "retrieve_event_properties",
                    "signature": "(event_name: str)",
                    "description": """
                        Use this tool to retrieve property names of an event that the user has in their taxonomy. You will receive a list of properties, their value types and example values or a message that properties have not been found.

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
                        Use this tool to retrieve property values for an event that the user has in their taxonomy. Adjust filters to these values. You will receive a list of property values or a message that property values have not been found. Some properties can have many values, so the output will be truncated. Use your judgement to find a proper value.

                        Args:
                            event_name: The name of the event that you want to retrieve values for.
                            property_name: The name of the property that you want to retrieve values for.
                    """,
                },
                {
                    "name": f"retrieve_entity_properties",
                    "signature": f"(entity: Literal[{stringified_entities}])",
                    "description": """
                        Use this tool to retrieve property names for a property group (entity) that the user has in their taxonomy. You will receive a list of properties and their value types or a message that properties have not been found.

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
                        Use this tool to retrieve property values for a property name that the user has in their taxonomy. Adjust filters to these values. You will receive a list of property values or a message that property values have not been found. Some properties can have many values, so the output will be truncated. Use your judgement to find a proper value.

                        Args:
                            entity: The type of the entity that you want to retrieve properties for.
                            property_name: The name of the property that you want to retrieve values for.
                    """,
                },
                {
                    "name": "final_answer",
                    "signature": "(final_response: str)",
                    "description": """
                        Use this tool to provide the final answer to the user's question.

                        Answer in the following format:
                        ```
                        Events:
                        - event 1
                            - math operation: total
                            - property filter 1:
                                - entity
                                - property name
                                - property type
                                - operator
                                - property value
                            - property filter 2... Repeat for each property filter.
                        - event 2
                            - math operation: average by `property name`.
                            - property filter 1:
                                - entity
                                - property name
                                - property type
                                - operator
                                - property value
                            - property filter 2... Repeat for each property filter.
                        - Repeat for each event.

                        (if a formula is used)
                        Formula:
                        `A/B`, where `A` is the first event and `B` is the second event.

                        (if a breakdown is used)
                        Breakdown by:
                        - breakdown 1:
                            - entity
                            - property name
                        - Repeat for each breakdown.
                        ```

                        Args:
                            final_response: List all events and properties that you want to use to answer the question.
                    """,
                },
            ]
        ]

        return tools

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
        descriptions = []
        for tool in self.tools:
            description = f"{tool['name']}{tool['signature']} - {tool['description']}"
            descriptions.append(description)
        return "\n".join(descriptions)

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
                description = entity_definition.get("description")
            enriched_props.append((prop_name, prop_type, description))
        return enriched_props

    def retrieve_entity_properties(self, entity: str) -> str:
        """
        Retrieve properties for an entitiy like person, session, or one of the groups.
        """
        if entity not in ("person", "session", *[group.group_type for group in self.groups]):
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
                (group.group_type_index for group in self.groups if group.group_type == entity), None
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

    def retrieve_event_properties(self, event_name: str) -> str:
        """
        Retrieve properties for an event.
        """
        runner = EventTaxonomyQueryRunner(EventTaxonomyQuery(event=event_name), self._team)
        response = runner.run(ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS)

        if not isinstance(response, CachedEventTaxonomyQueryResponse):
            return "Properties have not been found."

        if not response.results:
            return f"Properties do not exist in the taxonomy for the event {event_name}."

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
            return f"Properties do not exist in the taxonomy for the event {event_name}."

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

    def retrieve_event_property_values(self, event_name: str, property_name: str) -> str:
        try:
            property_definition = PropertyDefinition.objects.get(
                team=self._team, name=property_name, type=PropertyDefinition.Type.EVENT
            )
        except PropertyDefinition.DoesNotExist:
            return f"The property {property_name} does not exist in the taxonomy."

        runner = EventTaxonomyQueryRunner(EventTaxonomyQuery(event=event_name), self._team)
        response = runner.run(ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS)

        if not isinstance(response, CachedEventTaxonomyQueryResponse):
            return f"The event {event_name} does not exist in the taxonomy."

        if not response.results:
            return f"Property values for {property_name} do not exist in the taxonomy for the event {event_name}."

        prop = next((item for item in response.results if item.property == property_name), None)
        if not prop:
            return f"The property {property_name} does not exist in the taxonomy for the event {event_name}."

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
            sample_values = POSSIBLE_CHANNEL_TYPES.copy()
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
            query = ActorsPropertyTaxonomyQuery(property=property_name)
        else:
            group_index = next((group.group_type_index for group in self.groups if group.group_type == entity), None)
            if group_index is None:
                return f"The entity {entity} does not exist in the taxonomy."
            query = ActorsPropertyTaxonomyQuery(group_type_index=group_index, property=property_name)

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


class GenerateTrendTool:
    def _replace_value_in_dict(self, item: Any, original_schema: Any):
        if isinstance(item, list):
            return [self._replace_value_in_dict(i, original_schema) for i in item]
        elif isinstance(item, dict):
            if list(item.keys()) == ["$ref"]:
                definitions = item["$ref"][2:].split("/")
                res = original_schema.copy()
                for definition in definitions:
                    res = res[definition]
                return res
            else:
                return {key: self._replace_value_in_dict(i, original_schema) for key, i in item.items()}
        else:
            return item

    def _flatten_schema(self):
        schema = ExperimentalAITrendsQuery.model_json_schema()

        # Patch `numeric` types
        schema["$defs"]["MathGroupTypeIndex"]["type"] = "number"
        property_filters = (
            "EventPropertyFilter",
            "PersonPropertyFilter",
            "SessionPropertyFilter",
            "FeaturePropertyFilter",
            "GroupPropertyFilter",
        )

        # Clean up the property filters
        for key in property_filters:
            property_schema = schema["$defs"][key]
            property_schema["properties"]["key"]["description"] = (
                f"Use one of the properties the user has provided in the plan."
            )

        for _ in range(100):
            if "$ref" not in json.dumps(schema):
                break
            schema = self._replace_value_in_dict(schema.copy(), schema.copy())
        del schema["$defs"]
        return schema

    @cached_property
    def schema(self):
        return {
            "name": "output_insight_schema",
            "description": "Outputs the JSON schema of a product analytics insight",
            "parameters": {
                "type": "object",
                "properties": {
                    "reasoning_steps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "The reasoning steps leading to the final conclusion that will be shown to the user. Use 'you' if you want to refer to the user.",
                    },
                    "answer": self._flatten_schema(),
                },
                "additionalProperties": False,
                "required": ["reasoning_steps", "answer"],
            },
        }
