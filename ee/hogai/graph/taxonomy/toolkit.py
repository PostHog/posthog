import asyncio
from collections.abc import Iterable
from functools import cached_property
from typing import Any, Optional, Union, cast

from langchain_core.agents import AgentAction
from pydantic import BaseModel

from posthog.schema import (
    ActorsPropertyTaxonomyQuery,
    CachedActorsPropertyTaxonomyQueryResponse,
    CachedEventTaxonomyQueryResponse,
    CacheMissResponse,
    EventTaxonomyItem,
    EventTaxonomyQuery,
    QueryStatusResponse,
)

from posthog.hogql.database.schema.channel_type import DEFAULT_CHANNEL_TYPES

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.hogql_queries.ai.actors_property_taxonomy_query_runner import ActorsPropertyTaxonomyQueryRunner
from posthog.hogql_queries.ai.event_taxonomy_query_runner import EventTaxonomyQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Action, Team
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.property_definition import PropertyDefinition, PropertyType
from posthog.sync import database_sync_to_async
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
        self.MAX_ENTITIES_PER_BATCH = 6

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
            *self._team_group_types,
        ]
        return entities

    @database_sync_to_async(thread_sensitive=False)
    def _get_entity_names(self) -> list[str]:
        return self._entity_names

    def _enrich_props_with_descriptions(self, entity: str, props: Iterable[tuple[str, str | None]]):
        return enrich_props_with_descriptions(entity, props)

    def _format_property_values(
        self, property_name: str, sample_values: list, sample_count: Optional[int] = 0, format_as_string: bool = False
    ) -> str:
        return format_property_values(property_name, sample_values, sample_count, format_as_string)

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

        return self._format_property_values(property_name, sample_values, sample_count, format_as_string=is_str)

    @database_sync_to_async(thread_sensitive=False)
    def _retrieve_event_or_action_taxonomy(
        self, event_name_or_action_id: str | int, properties: list[str] | None = None
    ):
        """
        Retrieve event/action taxonomy with efficient caching.
        Multiple properties are batched in a single query to maximize cache hits.
        """
        is_event = isinstance(event_name_or_action_id, str)
        if is_event:
            query = EventTaxonomyQuery(event=event_name_or_action_id, maxPropertyValues=25, properties=properties)
            verbose_name = f"event {event_name_or_action_id}"
        else:
            query = EventTaxonomyQuery(actionId=event_name_or_action_id, maxPropertyValues=25, properties=properties)
            verbose_name = f"action with ID {event_name_or_action_id}"
        runner = EventTaxonomyQueryRunner(query, self._team)
        with tags_context(product=Product.MAX_AI, team_id=self._team.pk, org_id=self._team.organization_id):
            # Use cache-first execution mode for optimal performance
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

    async def retrieve_entity_properties(self, entity: str, max_properties: int = 500) -> str:
        """
        Retrieve properties for an entitiy like person, session, or one of the groups.
        """
        entity_names = await self._get_entity_names()
        if entity not in entity_names:
            return TaxonomyErrorMessages.entity_not_found(entity, entity_names)

        props: list[Any] = []
        if entity == "person":
            qs = PropertyDefinition.objects.filter(team=self._team, type=PropertyDefinition.Type.PERSON).values_list(
                "name", "property_type"
            )
            props = self._enrich_props_with_descriptions("person", [prop async for prop in qs])
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
            group_type_index = None
            groups = [group async for group in self._groups]
            for group in groups:
                if group.group_type == entity:
                    group_type_index = group.group_type_index
                    break
            if group_type_index is None:
                return f"Group {entity} does not exist in the taxonomy."
            qs = PropertyDefinition.objects.filter(
                team=self._team, type=PropertyDefinition.Type.GROUP, group_type_index=group_type_index
            ).values_list("name", "property_type")[:max_properties]
            props = self._enrich_props_with_descriptions(entity, [prop async for prop in qs])

        if not props:
            return f"Properties do not exist in the taxonomy for the entity {entity}."

        return self._format_properties(props)

    async def retrieve_entity_property_values(self, entity_properties: dict[str, list[str]]) -> dict[str, list[str]]:
        result = await self._parallel_entity_processing(entity_properties)
        return result

    async def _handle_entity_batch(self, batch: dict[str, list[str]]) -> dict[str, list[str]]:
        entity_tasks = [
            self._retrieve_multiple_entity_property_values(entity, property_names)
            for entity, property_names in batch.items()
        ]
        batch_results = await asyncio.gather(*entity_tasks)
        return dict(zip(batch.keys(), batch_results))

    async def _parallel_entity_processing(self, entity_properties: dict[str, list[str]]) -> dict[str, list[str]]:
        entity_items = list(entity_properties.items())
        if len(entity_items) > self.MAX_ENTITIES_PER_BATCH:
            # Process in batches
            results = {}
            for i in range(0, len(entity_items), self.MAX_ENTITIES_PER_BATCH):
                batch = dict(entity_items[i : i + self.MAX_ENTITIES_PER_BATCH])
                batch_results = await self._handle_entity_batch(batch)
                results.update(batch_results)
            return results
        else:
            return await self._handle_entity_batch(entity_properties)

    async def _retrieve_multiple_entity_property_values(self, entity: str, property_names: list[str]) -> list[str]:
        """Retrieve property values for multiple entities and properties efficiently."""
        results = []
        entity_names = await self._get_entity_names()
        if entity not in entity_names:
            results.append(TaxonomyErrorMessages.entity_not_found(entity, entity_names))
            return results
        if entity == "session":
            for property_name in property_names:
                results.append(self._retrieve_session_properties(property_name))
            return results
        groups = [group async for group in self._groups]
        query = self._build_query(entity, property_names, groups)
        if query is None:
            results.append(TaxonomyErrorMessages.entity_not_found(entity))
            return results
        property_values_response = await self._run_actors_taxonomy_query(query)
        if not isinstance(property_values_response, CachedActorsPropertyTaxonomyQueryResponse):
            results.append(TaxonomyErrorMessages.entity_not_found(entity))
            return results

        if not property_values_response.results:
            for property_name in property_names:
                results.append(TaxonomyErrorMessages.property_values_not_found(property_name, entity))
            return results

        if isinstance(property_values_response.results, list):
            property_values_results = property_values_response.results
        else:
            property_values_results = [property_values_response.results]

        property_definitions: dict[str, PropertyDefinition] = await self._get_definitions_for_entity(
            entity, property_names, query
        )

        results.extend(
            self._process_property_values(
                property_names, property_values_results, property_definitions, entity, is_indexed=True
            )
        )
        return results

    @database_sync_to_async(thread_sensitive=False)
    def _get_definitions_for_entity(
        self, entity: str, property_names: list[str], query: ActorsPropertyTaxonomyQuery
    ) -> dict[str, PropertyDefinition]:
        """Get property definitions for one entity and properties."""
        if not property_names:
            return {}

        if query.groupTypeIndex is not None:
            prop_type = PropertyDefinition.Type.GROUP
            group_type_index = query.groupTypeIndex
        elif entity == "event":
            prop_type = PropertyDefinition.Type.EVENT
            group_type_index = None
        else:
            prop_type = PropertyDefinition.Type.PERSON
            group_type_index = None

        property_definitions = PropertyDefinition.objects.filter(
            team=self._team,
            name__in=property_names,
            type=prop_type,
            group_type_index=group_type_index,
        )
        return {prop.name: prop for prop in property_definitions}

    def _build_query(
        self, entity: str, properties: list[str], groups: list[GroupTypeMapping]
    ) -> ActorsPropertyTaxonomyQuery | None:
        """Build a query for the given entity and property names."""
        if entity == "person":
            query = ActorsPropertyTaxonomyQuery(properties=properties, maxPropertyValues=25)
        elif entity == "event":
            query = ActorsPropertyTaxonomyQuery(properties=properties, maxPropertyValues=50)
        else:
            group_index = next((group.group_type_index for group in groups if group.group_type == entity), None)
            if group_index is None:
                return None
            query = ActorsPropertyTaxonomyQuery(groupTypeIndex=group_index, properties=properties, maxPropertyValues=25)
        return query

    @database_sync_to_async(thread_sensitive=False)
    def _run_actors_taxonomy_query(
        self, query
    ) -> CachedActorsPropertyTaxonomyQueryResponse | CacheMissResponse | QueryStatusResponse:
        with tags_context(product=Product.MAX_AI, team_id=self._team.pk, org_id=self._team.organization_id):
            return ActorsPropertyTaxonomyQueryRunner(query, self._team).run(
                ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS
            )

    @database_sync_to_async(thread_sensitive=False)
    def _get_project_actions(self) -> list[Action]:
        return list(Action.objects.filter(team__project_id=self._team.project_id, deleted=False))

    async def retrieve_event_or_action_properties(self, event_name_or_action_id: str | int) -> str:
        """
        Retrieve properties for an event.
        """
        try:
            response, verbose_name = await self._retrieve_event_or_action_taxonomy(event_name_or_action_id)
        except Action.DoesNotExist:
            project_actions = await self._get_project_actions()
            if not project_actions:
                return TaxonomyErrorMessages.no_actions_exist()
            return TaxonomyErrorMessages.action_not_found(event_name_or_action_id)
        if not isinstance(response, CachedEventTaxonomyQueryResponse):
            return TaxonomyErrorMessages.generic_not_found("Properties")
        if not response.results:
            return TaxonomyErrorMessages.event_properties_not_found(verbose_name)

        qs = PropertyDefinition.objects.filter(
            team=self._team, type=PropertyDefinition.Type.EVENT, name__in=[item.property for item in response.results]
        )
        property_data = [prop async for prop in qs]
        property_to_type = {prop.name: prop.property_type for prop in property_data}
        props = [
            (item.property, property_to_type.get(item.property))
            for item in response.results
            # Exclude properties that exist in the taxonomy, but don't have a type.
            if item.property in property_to_type
        ]

        if not props:
            return TaxonomyErrorMessages.event_properties_not_found(verbose_name)
        enriched_props = self._enrich_props_with_descriptions("event", props)
        return self._format_properties(enriched_props)

    async def retrieve_event_or_action_property_values(
        self, event_properties: dict[str | int, list[str]]
    ) -> dict[str | int, list[str]]:
        """Retrieve property values for an event/action. Supports single property or list of properties."""
        result = await self._parallel_event_processing(event_properties)
        return result

    async def _parallel_event_processing(
        self, event_properties: dict[str | int, list[str]]
    ) -> dict[str | int, list[str]]:
        event_tasks = [
            self._retrieve_multiple_event_or_action_property_values(event_name_or_action_id, property_names)
            for event_name_or_action_id, property_names in event_properties.items()
        ]
        results = await asyncio.gather(*event_tasks)
        return dict(zip(event_properties.keys(), results))

    @database_sync_to_async(thread_sensitive=False)
    def _get_definitions_for_event_or_action(self, property_names: list[str]) -> dict[str, PropertyDefinition]:
        return {
            prop.name: prop
            for prop in PropertyDefinition.objects.filter(
                team=self._team,
                name__in=property_names,
                type=PropertyDefinition.Type.EVENT,
            )
        }

    async def _retrieve_multiple_event_or_action_property_values(
        self, event_name_or_action_id: str | int, property_names: list[str]
    ) -> list[str]:
        """Retrieve property values for multiple events/actions and properties efficiently."""
        results = []
        try:
            definitions_map: dict[str, PropertyDefinition] = await self._get_definitions_for_event_or_action(
                property_names
            )
        except PropertyDefinition.DoesNotExist:
            definitions_map = {}

        response, verbose_name = await self._retrieve_event_or_action_taxonomy(event_name_or_action_id, property_names)

        if not isinstance(response, CachedEventTaxonomyQueryResponse):
            results.append(TaxonomyErrorMessages.event_not_found(verbose_name))
            return results
        if not response.results:
            for property_name in property_names:
                results.append(TaxonomyErrorMessages.property_values_not_found(property_name, verbose_name))
            return results

        # Create a map of property name to taxonomy result for efficient lookup
        taxonomy_results_map: dict[str, EventTaxonomyItem] = {item.property: item for item in response.results}

        results.extend(
            self._process_property_values(
                property_names, list(taxonomy_results_map.values()), definitions_map, verbose_name, is_indexed=False
            )
        )

        return results

    def _process_property_values(
        self,
        property_names: list[str],
        property_results: list,
        property_definitions: dict[str, PropertyDefinition],
        entity_name: str,
        is_indexed: bool = False,
    ) -> list[str]:
        """Common logic for processing property values from taxonomy results."""
        results = []

        for i, property_name in enumerate(property_names):
            property_definition = property_definitions.get(property_name)

            if property_definition is None:
                results.append(TaxonomyErrorMessages.property_not_found(property_name, entity_name))
                continue

            if is_indexed:
                if i >= len(property_results):
                    results.append(TaxonomyErrorMessages.property_not_found(property_name, entity_name))
                    continue
                prop_result = property_results[i]
            else:
                prop_result = next((r for r in property_results if r.property == property_name), None)
                if prop_result is None:
                    results.append(TaxonomyErrorMessages.property_not_found(property_name, entity_name))
                    continue

            result = self._format_property_values(
                property_name,
                prop_result.sample_values,
                prop_result.sample_count,
                format_as_string=property_definition.property_type in (PropertyType.String, PropertyType.Datetime),
            )
            results.append(result)

        return results

    async def handle_tools(self, tool_name: str, tool_input: TaxonomyTool) -> tuple[str, str]:
        if tool_name == "retrieve_entity_property_values":
            entity = tool_input.arguments.entity  # type: ignore
            property_name = tool_input.arguments.property_name  # type: ignore
            result = (await self.retrieve_entity_property_values({entity: [property_name]}))[entity][0]
        elif tool_name == "retrieve_entity_properties":
            result = await self.retrieve_entity_properties(tool_input.arguments.entity)  # type: ignore
        elif tool_name == "retrieve_event_property_values":
            event_name_or_action_id = tool_input.arguments.event_name  # type: ignore
            property_name = tool_input.arguments.property_name  # type: ignore
            result = (await self.retrieve_event_or_action_property_values({event_name_or_action_id: [property_name]}))[
                event_name_or_action_id
            ][0]
        elif tool_name == "retrieve_event_properties":
            result = await self.retrieve_event_or_action_properties(tool_input.arguments.event_name)  # type: ignore
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
