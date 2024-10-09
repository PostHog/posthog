import xml.etree.ElementTree as ET
from functools import cached_property
from typing import Literal, TypedDict, cast

from pydantic import BaseModel

from posthog.hogql_queries.ai.event_taxonomy_query_runner import EventTaxonomyQueryRunner
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.property_definition import PropertyDefinition
from posthog.models.team.team import Team
from posthog.schema import CachedEventTaxonomyQueryResponse, EventTaxonomyQuery


class ToolkitTool(TypedDict):
    name: str
    signature: str
    description: str


class TrendsAgentToolModel(BaseModel):
    name: Literal[
        "retrieve_entity_properties_tool",
        "retrieve_event_properties_tool",
        "retrieve_property_values_tool",
        "final_answer",
    ]
    argument: str


class TrendsAgentToolkit:
    _team: Team

    def __init__(self, team: Team):
        self._team = team

    @property
    def groups(self):
        return GroupTypeMapping.objects.filter(team=self._team).order_by("group_type_index")

    @cached_property
    def tools(self) -> list[ToolkitTool]:
        """
        Our ReAct agent doesn't use function calling. Instead, it uses tools in natural language to decide next steps. The agent expects the following format:

        ```
        retrieve_entity_properties_tool(entity: "Literal['person', 'session', 'cohort', 'organization', 'instance', 'project']") - description.
        ```

        Events and other entities are intentionally separated for properties retrieval. Potentially, there can be different functions for each entity type.
        """

        entities = [
            "person",
            "session",
            # "cohort", # not supported yet
            *[group.group_type for group in self.groups],
        ]
        stringified_entities = ", ".join([f"'{entity}'" for entity in entities])

        return [
            {
                "name": f"retrieve_entity_properties_tool",
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
                "name": "retrieve_event_properties_tool",
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
                "name": "retrieve_property_values_tool",
                "signature": "(property_name: str)",
                "description": """
                    Use this tool to retrieve property values for a property name that the user has in their taxonomy. Adjust filters to these values. You will receive a list of property values or a message that property values have not been found. Some properties can have many values, so the output will be truncated. Use your judgement to find a proper value.

                    Args:
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
                        final_response: List all events, actions, and properties that you want to use to answer the question.
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
        descriptions = []
        for tool in self.tools:
            description = f"{tool['name']}{tool['signature']} - {tool['description']}"
            descriptions.append(description)
        return "\n".join(descriptions)

    def _generate_properties_xml(self, children: list[tuple[str, str | None]]):
        root = ET.Element("properties")
        property_types = {property_type for _, property_type in children if property_type is not None}
        property_type_to_tag = {property_type: ET.SubElement(root, property_type) for property_type in property_types}

        for name, property_type in children:
            # Do not include properties that are ambiguous.
            if property_type is None:
                continue

            type_tag = property_type_to_tag[property_type]
            ET.SubElement(type_tag, "name").text = name
            # Add a line break between names. Doubtful that it does anything.
            ET.SubElement(type_tag, "br")

        return ET.tostring(root, encoding="unicode")

    def retrieve_entity_properties(self, entity: str):
        """
        Retrieve properties for an entitiy like person, session, or one of the groups.
        """
        if entity not in ("person", "session", *[group.group_type for group in self.groups]):
            return f"Entity {entity} does not exist in the taxonomy."

        if entity == "person":
            qs = PropertyDefinition.objects.filter(team=self._team, type=PropertyDefinition.Type.PERSON)
        elif entity == "session":
            qs = PropertyDefinition.objects.filter(team=self._team, type=PropertyDefinition.Type.SESSION)
        else:
            group_type_index = next(
                (group.group_type_index for group in self.groups if group.group_type == entity), None
            )
            if group_type_index is None:
                return f"Group {entity} does not exist in the taxonomy."
            qs = PropertyDefinition.objects.filter(
                team=self._team, type=PropertyDefinition.Type.GROUP, group_type_index=group_type_index
            )

        return self._generate_properties_xml(list(qs.values_list("name", "property_type")))

    def retrieve_event_properties(self, event_name: str):
        """
        Retrieve properties for an event.
        """
        runner = EventTaxonomyQueryRunner(EventTaxonomyQuery(event=event_name), self._team)
        response = runner.run()

        if "results" not in response:
            return "Properties have not been found."

        response = cast(CachedEventTaxonomyQueryResponse, response)
        if not response.results:
            return f"Properties do not exist in the taxonomy for the event {event_name}."

        # Intersect properties with their types.
        qs = PropertyDefinition.objects.filter(
            team=self._team, type=PropertyDefinition.Type.EVENT, name__in=[item.property for item in response.results]
        )
        property_to_type = {property_definition.name: property_definition.property_type for property_definition in qs}

        return self._generate_properties_xml(
            [
                (item.property, property_to_type.get(item.property))
                for item in response.results
                # Exclude properties that exist in the taxonomy, but don't have a type.
                if item.property in property_to_type
            ]
        )

    def retrieve_property_values_tool(self, property_name: str):
        # output values here with quotes for strings
        pass
