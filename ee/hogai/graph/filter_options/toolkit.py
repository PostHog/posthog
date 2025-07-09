from collections.abc import Iterable
from posthog.models import Team
from posthog.models.property_definition import PropertyDefinition
from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP
from functools import cached_property
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.hogql_queries.ai.actors_property_taxonomy_query_runner import ActorsPropertyTaxonomyQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.schema import ActorsPropertyTaxonomyQuery, CachedActorsPropertyTaxonomyQueryResponse
from posthog.models.property_definition import PropertyType
from typing import Optional
from pydantic import BaseModel, Field


class ask_user_for_help(BaseModel):
    """
    Use this tool to ask a clarifying question to the user. Your question must be concise and clear.
    """

    request: str = Field(..., description="The question you want to ask the user.")


class retrieve_entity_properties(BaseModel):
    """
    Use this tool to retrieve property names for a property group or entity when you know the entity type but you cannot correctly infer the property name.
    You get back a list of properties containing their name, value type, and description, or a message that properties have not been found.
    If you can't find any properties ask for clarification.
    If you find properties for the entity then infer which one is relevant to the user's question, use the property name in the `retrieve_entity_property_values` tool to get possible values for that property.
    """

    entity: str = Field(..., description="The name of the entity that you want to retrieve properties for.")


class retrieve_entity_property_values(BaseModel):
    """
    Use this tool to retrieve property values for an entity when you know the entity type and the property name.
    You get back a list of property values, or a message that property values have not been found.
    If you can't find any values, tell the user that you couldn't find any values and ask for clarification.
    If you find property values that are relevant to the user's question, use one of the values in the `final_answer` tool to build the filter.
    If the values are not relevant to the user's question, use the value that the user has provided in the query.
    """

    # This might fail for other entities, but we don't use this tool for other entities.
    entity: str = Field(..., description="The name of the entity that you want to retrieve properties for.")
    property_name: str = Field(..., description="The name of the property that you want to retrieve values for.")


class final_answer(BaseModel):
    """
    Use this tool to finalize the filter options answer.
    You MUST use this tool ONLY when you have all the information you need to build the filter.
    If you don't have all the information you need, use the `ask_user_for_help` tool to ask the user for clarification.
    """

    result: str = Field(description="Should be 'filter' for filter responses.")
    data: dict = Field(description="Complete filter object as defined in the prompts")


class FilterOptionsToolkit:
    _team: Team

    def __init__(self, team: Team):
        self._team = team

    @property
    def _groups(self):
        return GroupTypeMapping.objects.filter(project=self._team.project).order_by("group_type_index")

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
            "event",
            *[group.group_type for group in self._groups],
        ]
        return entities

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

    def _format_property_values(
        self, sample_values: list, sample_count: Optional[int] = 0, format_as_string: bool = False
    ) -> str:
        if len(sample_values) == 0 or sample_count == 0:
            return f"The property does not have any values in the taxonomy. Use the value that the user has provided in the query."

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

    def retrieve_entity_property_values(self, entity: str, property_name: str) -> str:
        """
        Retrieve property values for an entity and property name.
        """
        MAX_PROP_VALUES = 50
        if entity not in self._entity_names:
            return f"The entity {entity} does not exist in the taxonomy. Try one of these entities: {', '.join(self._entity_names)}."

        if entity == "person" or entity == "session":
            query = ActorsPropertyTaxonomyQuery(property=property_name, maxPropertyValues=MAX_PROP_VALUES)
        else:
            group_index = next((group.group_type_index for group in self._groups if group.group_type == entity), None)
            if group_index is None:
                return f"The entity {entity} does not exist in the taxonomy."
            query = ActorsPropertyTaxonomyQuery(
                group_type_index=group_index, property=property_name, maxPropertyValues=MAX_PROP_VALUES
            )

        try:
            if query.group_type_index is not None:
                prop_type = PropertyDefinition.Type.GROUP
                group_type_index = query.group_type_index
            elif entity == "person":
                prop_type = PropertyDefinition.Type.PERSON
                group_type_index = None
            elif entity == "session":
                prop_type = PropertyDefinition.Type.SESSION
                group_type_index = None

            property_definition = PropertyDefinition.objects.get(
                team=self._team,
                name=property_name,
                type=prop_type,
                group_type_index=group_type_index,
            )
        except PropertyDefinition.DoesNotExist:
            return f"The property {property_name} does not exist in the taxonomy for the entity {entity}. Try another property that is relevant to the user's question."

        response = ActorsPropertyTaxonomyQueryRunner(query, self._team).run(
            ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS
        )

        if not isinstance(response, CachedActorsPropertyTaxonomyQueryResponse):
            return f"The entity {entity} does not exist in the taxonomy."

        if not response.results:
            return f"Property values for {property_name} do not exist in the taxonomy for the entity {entity}. Use the value that the user has provided in the query."

        return self._format_property_values(
            response.results.sample_values,
            response.results.sample_count,
            format_as_string=property_definition.property_type in (PropertyType.String, PropertyType.Datetime),
        )

    def retrieve_entity_properties(self, entity: str) -> str:
        """
        Retrieve properties for an entitiy like person, session, event, or one of the groups.
        """
        MAX_PROPERTIES = 500
        if entity not in self._entity_names:
            return f"Entity '{entity}' does not exist. Available entities are: {', '.join(self._entity_names)}. Try one of these other entities."

        if entity == "person":
            qs = PropertyDefinition.objects.filter(team=self._team, type=PropertyDefinition.Type.PERSON).values_list(
                "name", "property_type"
            )[:MAX_PROPERTIES]
            props = self._enrich_props_with_descriptions("person", qs)
        elif entity == "session":
            props = self._enrich_props_with_descriptions(
                "session",
                [
                    (prop_name, prop["type"])
                    for prop_name, prop in CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"].items()
                    if prop.get("type") is not None
                ],
            )
            # props = self._enrich_props_with_descriptions("session", qs)
        elif entity == "event":
            qs = PropertyDefinition.objects.filter(team=self._team, type=PropertyDefinition.Type.EVENT).values_list(
                "name", "property_type"
            )[:MAX_PROPERTIES]
            props = self._enrich_props_with_descriptions("event", qs)
        else:
            group_type_index = next(
                (group.group_type_index for group in self._groups if group.group_type == entity), None
            )
            if group_type_index is None:
                return f"Group {entity} does not exist in the taxonomy. Try one of these other groups: {', '.join([group.group_type for group in self._groups])}."
            qs = PropertyDefinition.objects.filter(
                team=self._team, type=PropertyDefinition.Type.GROUP, group_type_index=group_type_index
            ).values_list("name", "property_type")[:MAX_PROPERTIES]
            props = self._enrich_props_with_descriptions(entity, qs)

        if not props:
            return f"Properties do not exist in the taxonomy for the entity {entity}. Try one of these other entities: {', '.join(self._entity_names)}."

        return self._generate_properties_yaml(props)

    def handle_incorrect_response(self, response: BaseModel) -> str:
        """
        No-op tool. Take a parsing error and return a response that the LLM can use to correct itself.
        Used to control a number of retries.
        """
        return response.model_dump_json()
