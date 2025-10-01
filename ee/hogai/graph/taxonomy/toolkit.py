from collections.abc import Iterable
from functools import cached_property
from typing import Any, Optional, Union, cast

from langchain_core.agents import AgentAction
from pydantic import BaseModel

from posthog.schema import (
    ActorsPropertyTaxonomyQuery,
    CachedActorsPropertyTaxonomyQueryResponse,
    CachedEventTaxonomyQueryResponse,
    EventTaxonomyQuery,
)

from posthog.hogql.database.schema.channel_type import DEFAULT_CHANNEL_TYPES

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.hogql_queries.ai.actors_property_taxonomy_query_runner import ActorsPropertyTaxonomyQueryRunner
from posthog.hogql_queries.ai.event_taxonomy_query_runner import EventTaxonomyQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Action, Team
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.property_definition import PropertyDefinition, PropertyType
from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP

from ee.hogai.graph.taxonomy.format import (
    enrich_props_with_descriptions,
    format_properties_xml,
    format_properties_yaml,
    format_property_values,
)

from .tools import (
    TaxonomyTool,
    ask_user_for_help,
    retrieve_entity_properties,
    retrieve_entity_property_values,
    retrieve_event_properties,
    retrieve_event_property_values,
)


class TaxonomyToolNotFoundError(Exception):
    """Exception raised when a tool is not found in the taxonomy toolkit."""

    pass


class TaxonomyErrorMessages:
    """Standardized error messages for taxonomy operations."""

    @staticmethod
    def entity_not_found(entity: str, available_entities: list[str] | None = None) -> str:
        """Standard message for when an entity doesn't exist."""
        if available_entities:
            return f"Entity {entity} not found. Available entities: {', '.join(available_entities)}"
        return f"Entity {entity} not found in taxonomy"

    @staticmethod
    def property_not_found(property_name: str, entity: str | None = None) -> str:
        """Standard message for when a property doesn't exist."""
        if entity:
            return f"The property {property_name} does not exist in the taxonomy for entity {entity}."
        return f"The property {property_name} does not exist in the taxonomy."

    @staticmethod
    def properties_not_found(entity: str) -> str:
        """Standard message for when no properties exist for an entity."""
        return f"Properties do not exist in the taxonomy for the entity {entity}."

    @staticmethod
    def property_values_not_found(property_name: str, entity: str) -> str:
        """Standard message for when property values don't exist."""
        return f"No values found for property {property_name} on entity {entity}"

    @staticmethod
    def action_not_found(action_id: str | int) -> str:
        """Standard message for when an action doesn't exist."""
        return f"Action {action_id} does not exist in the taxonomy. Verify that the action ID is correct and try again."

    @staticmethod
    def no_actions_exist() -> str:
        """Standard message for when no actions exist in the project."""
        return "No actions exist in the project."

    @staticmethod
    def event_not_found(event_name: str) -> str:
        """Standard message for when an event doesn't exist."""
        return f"Event {event_name} not found in taxonomy"

    @staticmethod
    def generic_not_found(item_type: str) -> str:
        """Generic not found message."""
        return f"{item_type} not found"

    @staticmethod
    def event_properties_not_found(event_name: str) -> str:
        """Standard message for when no properties exist for an event/action."""
        return f"Properties do not exist in the taxonomy for the {event_name}."


class TaxonomyAgentToolkit:
    """Base toolkit for taxonomy agents that handle tool execution."""

    def __init__(self, team: Team):
        self._team = team

    @property
    def _groups(self):
        return GroupTypeMapping.objects.filter(project_id=self._team.project_id).order_by("group_type_index")

    @cached_property
    def _team_group_types(self) -> list[str]:
        """Get all available group names for this team."""
        return list(self._groups.values_list("group_type", flat=True))

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

    def _enrich_props_with_descriptions(self, entity: str, props: Iterable[tuple[str, str | None]]):
        return enrich_props_with_descriptions(entity, props)

    def _format_property_values(
        self, sample_values: list, sample_count: Optional[int] = 0, format_as_string: bool = False
    ) -> str:
        return format_property_values(sample_values, sample_count, format_as_string)

    def _retrieve_session_properties(self, property_name: str) -> str:
        """
        Sessions properties example property values are hardcoded.
        """
        if property_name not in CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"]:
            return TaxonomyErrorMessages.property_not_found(property_name)

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
            return TaxonomyErrorMessages.property_values_not_found(property_name, "session")

        return self._format_property_values(sample_values, sample_count, format_as_string=is_str)

    def _retrieve_event_or_action_taxonomy(self, event_name_or_action_id: str | int):
        is_event = isinstance(event_name_or_action_id, str)
        if is_event:
            query = EventTaxonomyQuery(event=event_name_or_action_id, maxPropertyValues=25)
            verbose_name = f"event {event_name_or_action_id}"
        else:
            query = EventTaxonomyQuery(actionId=event_name_or_action_id, maxPropertyValues=25)
            verbose_name = f"action with ID {event_name_or_action_id}"
        runner = EventTaxonomyQueryRunner(query, self._team)
        with tags_context(product=Product.MAX_AI, team_id=self._team.pk, org_id=self._team.organization_id):
            response = runner.run(ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS)
        return response, verbose_name

    def _format_properties(self, props: list[tuple[str, str | None, str | None]]) -> str:
        """
        Generate the output format for properties. Can be overridden by subclasses.
        Default implementation uses XML format.
        """
        return self._format_properties_xml(props)

    def _format_properties_xml(self, children: list[tuple[str, str | None, str | None]]):
        return format_properties_xml(children)

    def _format_properties_yaml(self, children: list[tuple[str, str | None, str | None]]):
        """
        Can be used in child classes to override the default implementation for `_format_properties` when yaml is desirable over XML
        """
        return format_properties_yaml(children)

    def handle_incorrect_response(self, response: BaseModel) -> str:
        """
        No-op tool. Take a parsing error and return a response that the LLM can use to correct itself.
        Used to control a number of retries.
        """
        return response.model_dump_json()

    def get_tools(self) -> list:
        """Get all tools (default + custom). Override in subclasses to add custom tools."""
        try:
            return [*self._get_default_tools(), *self._get_custom_tools()]
        except NotImplementedError:
            return self._get_default_tools()

    def _get_default_tools(self) -> list:
        """Get default taxonomy tools."""
        return [
            retrieve_event_properties,
            retrieve_entity_properties,
            retrieve_entity_property_values,
            retrieve_event_property_values,
            ask_user_for_help,
        ]

    def _get_custom_tools(self) -> list:
        """Get custom tools. Override in subclasses to add custom tools."""
        raise NotImplementedError("_get_custom_tools must be implemented in subclasses")

    def retrieve_entity_properties(self, entity: str, max_properties: int = 500) -> str:
        """
        Retrieve properties for an entitiy like person, session, or one of the groups.
        """

        if entity not in ("person", "session", *[group.group_type for group in self._groups]):
            return TaxonomyErrorMessages.entity_not_found(entity, self._entity_names)

        props: list[Any] = []
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
            ).values_list("name", "property_type")[:max_properties]
            props = self._enrich_props_with_descriptions(entity, qs)

        if not props:
            return f"Properties do not exist in the taxonomy for the entity {entity}."

        return self._format_properties(props)

    def retrieve_entity_property_values(self, entity: str, property_name: str) -> str:
        """Retrieve property values for an entity."""
        if entity not in self._entity_names:
            return TaxonomyErrorMessages.entity_not_found(entity, self._entity_names)

        if entity == "session":
            return self._retrieve_session_properties(property_name)

        if entity == "person":
            query = ActorsPropertyTaxonomyQuery(properties=[property_name], maxPropertyValues=25)
        elif entity == "event":
            query = ActorsPropertyTaxonomyQuery(properties=[property_name], maxPropertyValues=50)
        else:
            group_index = next((group.group_type_index for group in self._groups if group.group_type == entity), None)
            if group_index is None:
                return TaxonomyErrorMessages.entity_not_found(entity)
            query = ActorsPropertyTaxonomyQuery(
                groupTypeIndex=group_index, properties=[property_name], maxPropertyValues=25
            )

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
            return TaxonomyErrorMessages.property_not_found(property_name, entity)

        with tags_context(product=Product.MAX_AI, team_id=self._team.pk, org_id=self._team.organization_id):
            response = ActorsPropertyTaxonomyQueryRunner(query, self._team).run(
                ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS
            )

        if not isinstance(response, CachedActorsPropertyTaxonomyQueryResponse):
            return TaxonomyErrorMessages.entity_not_found(entity)

        if not response.results:
            return TaxonomyErrorMessages.property_values_not_found(property_name, entity)

        # TRICKY. Remove when the toolkit supports multiple results.
        if isinstance(response.results, list):
            unpacked_results = response.results[0]
        else:
            unpacked_results = response.results

        return self._format_property_values(
            unpacked_results.sample_values,
            unpacked_results.sample_count,
            format_as_string=property_definition.property_type in (PropertyType.String, PropertyType.Datetime),
        )

    def retrieve_event_or_action_properties(self, event_name_or_action_id: str | int) -> str:
        """
        Retrieve properties for an event.
        """
        try:
            response, verbose_name = self._retrieve_event_or_action_taxonomy(event_name_or_action_id)
        except Action.DoesNotExist:
            project_actions = Action.objects.filter(team__project_id=self._team.project_id, deleted=False)
            if not project_actions:
                return TaxonomyErrorMessages.no_actions_exist()
            return TaxonomyErrorMessages.action_not_found(event_name_or_action_id)
        if not isinstance(response, CachedEventTaxonomyQueryResponse):
            return TaxonomyErrorMessages.generic_not_found("Properties")
        if not response.results:
            return TaxonomyErrorMessages.event_properties_not_found(verbose_name)
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
            return TaxonomyErrorMessages.event_properties_not_found(verbose_name)
        return self._format_properties(self._enrich_props_with_descriptions("event", props))

    def retrieve_event_or_action_property_values(self, event_name_or_action_id: str | int, property_name: str) -> str:
        try:
            property_definition = PropertyDefinition.objects.get(
                team=self._team, name=property_name, type=PropertyDefinition.Type.EVENT
            )
        except PropertyDefinition.DoesNotExist:
            return TaxonomyErrorMessages.property_not_found(property_name)

        response, verbose_name = self._retrieve_event_or_action_taxonomy(event_name_or_action_id)
        if not isinstance(response, CachedEventTaxonomyQueryResponse):
            return TaxonomyErrorMessages.event_not_found(verbose_name)
        if not response.results:
            return TaxonomyErrorMessages.property_values_not_found(property_name, verbose_name)

        prop = next((item for item in response.results if item.property == property_name), None)
        if not prop:
            return TaxonomyErrorMessages.property_not_found(property_name, verbose_name)

        return self._format_property_values(
            prop.sample_values,
            prop.sample_count,
            format_as_string=property_definition.property_type in (PropertyType.String, PropertyType.Datetime),
        )

    def handle_tools(self, tool_name: str, tool_input: TaxonomyTool) -> tuple[str, str]:
        # Here we handle the tool execution for base taxonomy tools.
        if tool_name == "retrieve_entity_property_values":
            result = self.retrieve_entity_property_values(
                tool_input.arguments.entity,  # type: ignore
                tool_input.arguments.property_name,  # type: ignore
            )
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
        else:
            raise TaxonomyToolNotFoundError(f"Tool {tool_name} not found in taxonomy toolkit.")

        return tool_name, result

    def get_tool_input_model(self, action: AgentAction) -> TaxonomyTool:
        try:
            custom_tools = self._get_custom_tools()
        except NotImplementedError:
            custom_tools = []

        custom_tools_union = Union[tuple(custom_tools)] if custom_tools else BaseModel

        class DynamicToolInput(TaxonomyTool[custom_tools_union]):  # type: ignore
            pass

        return DynamicToolInput.model_validate({"name": action.tool, "arguments": action.tool_input})
