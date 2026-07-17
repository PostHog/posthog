import re
from collections.abc import Iterable
from functools import cached_property
from typing import Literal, Optional, Union, cast

from pydantic import BaseModel, field_validator

from posthog.schema import (
    ActorsPropertyTaxonomyQuery,
    CachedActorsPropertyTaxonomyQueryResponse,
    CachedEventTaxonomyQueryResponse,
    EventTaxonomyQuery,
)

from posthog.hogql.database.schema.channel_type import DEFAULT_CHANNEL_TYPES

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.event_usage import EventSource
from posthog.hogql_queries.ai.actors_property_taxonomy_query_runner import ActorsPropertyTaxonomyQueryRunner
from posthog.hogql_queries.ai.event_taxonomy_query_runner import EventTaxonomyQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team, User
from posthog.taxonomy.property_access import restricted_property_names
from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP, CoreFilterDefinition

from products.actions.backend.models.action import Action
from products.event_definitions.backend.models.property_definition import PropertyDefinition, PropertyType

from ee.hogai.chat_agent.taxonomy.format import enrich_props_with_descriptions
from ee.hogai.chat_agent.taxonomy.tools import (
    ask_user_for_help,
    retrieve_action_properties,
    retrieve_action_property_values,
    retrieve_entity_properties,
    retrieve_entity_property_values,
    retrieve_event_properties,
    retrieve_event_property_values,
)
from ee.hogai.chat_agent.taxonomy.virtual_properties import (
    PropertyDefinitionOrVirtual,
    get_virtual_property_definition,
    get_virtual_property_sample_values,
    list_virtual_properties,
    property_is_string_like,
    virtual_group_for_entity,
    virtual_property_no_values_message,
)
from ee.hogai.utils.prompt import format_prompt_string

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


PROPERTIES_EXAMPLE_PROMPT = """
The data format is as follows:
<Data type>
- $event – description text here
- another_event
</Data type>
...
---
Results:
{{{result}}}
""".strip()


class TaxonomyAgentToolkit:
    _team: Team
    _user: User

    def __init__(self, team: Team, user: User):
        self._team = team
        self._user = user

    def _restricted_property_names(self, property_type: PropertyDefinition.Type) -> set[str]:
        return restricted_property_names(self._team, self._user, property_type)

    @cached_property
    def _groups(self) -> list[dict]:
        from posthog.models.group_type_mapping import get_group_types_for_project

        return get_group_types_for_project(self._team.project_id)

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
            *[g["group_type"] for g in self._groups],
        ]
        return entities

    def _generate_properties_output(self, props: list[tuple[str, str | None, str | None]]) -> str:
        """
        Generate the output format for properties. Can be overridden by subclasses.
        Default implementation uses YAML-like format with bullet points.
        """
        property_type_to_props: dict[str, list[tuple[str, str | None]]] = {}

        for name, property_type, description in props:
            # Do not include properties that are ambiguous.
            if property_type is None:
                continue
            if property_type not in property_type_to_props:
                property_type_to_props[property_type] = []

            property_type_to_props[property_type].append((name, description))

        output_parts = []
        for property_type, prop_list in property_type_to_props.items():
            output_parts.append(f"<{property_type}>")
            for name, description in prop_list:
                if description:
                    output_parts.append(f"- {name} – {description.replace('\n', ' ')}")
                else:
                    output_parts.append(f"- {name}")
            output_parts.append(f"</{property_type}>")

        return "\n".join(output_parts)

    def _enrich_props_with_descriptions(self, entity: str, props: Iterable[tuple[str, str | None]]):
        return enrich_props_with_descriptions(entity, props)

    def retrieve_entity_properties(self, entity: str, max_properties: int = 500) -> str:
        """
        Retrieve properties for an entitiy like person, session, or one of the groups.
        """

        if entity not in ("person", "session", *[g["group_type"] for g in self._groups]):
            return f"Entity {entity} does not exist in the taxonomy."

        if entity == "person":
            restricted = self._restricted_property_names(PropertyDefinition.Type.PERSON)
            stored_props = [
                p
                for p in PropertyDefinition.objects.filter(
                    team=self._team, type=PropertyDefinition.Type.PERSON
                ).values_list("name", "property_type")
                if p[0] not in restricted
            ]
            stored_props += list_virtual_properties(
                "person_properties", exclude={name for name, _ in stored_props} | restricted
            )
            props = self._enrich_props_with_descriptions("person", stored_props)
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
            group_type_index = next((g["group_type_index"] for g in self._groups if g["group_type"] == entity), None)
            if group_type_index is None:
                return f"Group {entity} does not exist in the taxonomy."
            restricted = self._restricted_property_names(PropertyDefinition.Type.GROUP)
            stored_props = [
                p
                for p in PropertyDefinition.objects.filter(
                    team=self._team, type=PropertyDefinition.Type.GROUP, group_type_index=group_type_index
                ).values_list("name", "property_type")[:max_properties]
                if p[0] not in restricted
            ]
            stored_props += list_virtual_properties("groups", exclude={name for name, _ in stored_props} | restricted)
            props = self._enrich_props_with_descriptions(entity, stored_props)

        if not props:
            return f"Properties do not exist in the taxonomy for the entity {entity}."

        return format_prompt_string(PROPERTIES_EXAMPLE_PROMPT, result=self._generate_properties_output(props))

    def _retrieve_event_or_action_taxonomy(self, event_name_or_action_id: str | int):
        is_event = isinstance(event_name_or_action_id, str)
        if is_event:
            query = EventTaxonomyQuery(event=event_name_or_action_id, maxPropertyValues=25)
            verbose_name = f"event {event_name_or_action_id}"
        else:
            query = EventTaxonomyQuery(actionId=event_name_or_action_id, maxPropertyValues=25)
            verbose_name = f"action with ID {event_name_or_action_id}"
        runner = EventTaxonomyQueryRunner(query, self._team, user=self._user)
        with tags_context(
            product=Product.MAX_AI,
            feature=Feature.POSTHOG_AI,
            team_id=self._team.pk,
            org_id=self._team.organization_id,
        ):
            response = runner.run(
                ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS,
                analytics_props={"source": EventSource.POSTHOG_AI},
            )
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
        restricted = self._restricted_property_names(PropertyDefinition.Type.EVENT)
        qs = PropertyDefinition.objects.filter(
            team=self._team, type=PropertyDefinition.Type.EVENT, name__in=[item.property for item in response.results]
        )
        property_to_type = {
            property_definition.name: property_definition.property_type
            for property_definition in qs
            if property_definition.name not in restricted
        }
        props: list[tuple[str, str | None]] = [
            (item.property, property_to_type.get(item.property))
            for item in response.results
            # Exclude properties that exist in the taxonomy, but don't have a type.
            if item.property in property_to_type
        ]
        # Virtual properties are computed at query time, so they never appear in stored event data.
        props += list_virtual_properties("event_properties", exclude=property_to_type.keys() | restricted)

        if not props:
            return f"Properties do not exist in the taxonomy for the {verbose_name}."

        return format_prompt_string(
            PROPERTIES_EXAMPLE_PROMPT,
            result=self._generate_properties_output(self._enrich_props_with_descriptions("event", props)),
        )

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

    def _format_virtual_property_values(self, property_name: str, property_definition: CoreFilterDefinition) -> str:
        sample_values, sample_count = get_virtual_property_sample_values(property_definition)
        if not sample_values:
            return virtual_property_no_values_message(property_name)
        return self._format_property_values(
            sample_values, sample_count, format_as_string=property_is_string_like(property_definition)
        )

    def retrieve_event_or_action_property_values(self, event_name_or_action_id: str | int, property_name: str) -> str:
        # Restricted properties are indistinguishable from non-existent ones, so we don't leak their values.
        if property_name in self._restricted_property_names(PropertyDefinition.Type.EVENT):
            return f"The property {property_name} does not exist in the taxonomy."
        virtual_definition = get_virtual_property_definition("event_properties", property_name)
        property_definition: PropertyDefinitionOrVirtual
        try:
            property_definition = PropertyDefinition.objects.get(
                team=self._team, name=property_name, type=PropertyDefinition.Type.EVENT
            )
        except PropertyDefinition.DoesNotExist:
            if virtual_definition is None:
                return f"The property {property_name} does not exist in the taxonomy."
            property_definition = virtual_definition

        response, verbose_name = self._retrieve_event_or_action_taxonomy(event_name_or_action_id)
        if not isinstance(response, CachedEventTaxonomyQueryResponse):
            return f"The {verbose_name} does not exist in the taxonomy."

        prop = next((item for item in response.results or [] if item.property == property_name), None)
        if not prop:
            # Virtual properties never appear in stored event data, so fall back to taxonomy examples.
            if virtual_definition is not None:
                return self._format_virtual_property_values(property_name, virtual_definition)
            if not response.results:
                return f"Property values for {property_name} do not exist in the taxonomy for the {verbose_name}."
            return f"The property {property_name} does not exist in the taxonomy for the {verbose_name}."

        return self._format_property_values(
            prop.sample_values,
            prop.sample_count,
            format_as_string=property_is_string_like(property_definition),
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

        # Restricted properties are indistinguishable from non-existent ones, so we don't leak their values.
        restricted_type = PropertyDefinition.Type.PERSON if entity == "person" else PropertyDefinition.Type.GROUP
        if property_name in self._restricted_property_names(restricted_type):
            return f"The property {property_name} does not exist in the taxonomy for the entity {entity}."

        if entity == "person":
            query = ActorsPropertyTaxonomyQuery(properties=[property_name], maxPropertyValues=25)
        elif entity == "event":
            query = ActorsPropertyTaxonomyQuery(properties=[property_name], maxPropertyValues=50)
        else:
            group_index = next((g["group_type_index"] for g in self._groups if g["group_type"] == entity), None)
            if group_index is None:
                return f"The entity {entity} does not exist in the taxonomy."
            query = ActorsPropertyTaxonomyQuery(
                groupTypeIndex=group_index, properties=[property_name], maxPropertyValues=25
            )

        virtual_definition = get_virtual_property_definition(virtual_group_for_entity(entity), property_name)
        property_definition: PropertyDefinitionOrVirtual
        try:
            if query.groupTypeIndex is not None:
                prop_type = PropertyDefinition.Type.GROUP
                group_type_index = query.groupTypeIndex
            elif entity == "event":
                prop_type = PropertyDefinition.Type.EVENT
                group_type_index = None
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
            if virtual_definition is None:
                return f"The property {property_name} does not exist in the taxonomy for the entity {entity}."
            property_definition = virtual_definition

        with tags_context(
            product=Product.MAX_AI,
            feature=Feature.POSTHOG_AI,
            team_id=self._team.pk,
            org_id=self._team.organization_id,
        ):
            response = ActorsPropertyTaxonomyQueryRunner(query, self._team, user=self._user).run(
                ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS,
                analytics_props={"source": EventSource.POSTHOG_AI},
            )

        if not isinstance(response, CachedActorsPropertyTaxonomyQueryResponse):
            return f"The entity {entity} does not exist in the taxonomy."

        if not response.results:
            if virtual_definition is not None:
                return self._format_virtual_property_values(property_name, virtual_definition)
            return f"Property values for {property_name} do not exist in the taxonomy for the entity {entity}."

        # TRICKY. Remove when the toolkit supports multiple results.
        if isinstance(response.results, list):
            unpacked_results = response.results[0]
        else:
            unpacked_results = response.results

        # Virtual properties never appear in stored actor data, so fall back to taxonomy examples.
        if not unpacked_results.sample_values and virtual_definition is not None:
            return self._format_virtual_property_values(property_name, virtual_definition)

        return self._format_property_values(
            unpacked_results.sample_values,
            unpacked_results.sample_count,
            format_as_string=property_is_string_like(property_definition),
        )

    def handle_incorrect_response(self, response: BaseModel) -> str:
        """
        No-op tool. Take a parsing error and return a response that the LLM can use to correct itself.
        Used to control a number of retries.
        """
        return response.model_dump_json()
