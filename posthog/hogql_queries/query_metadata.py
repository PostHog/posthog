from datetime import datetime, timedelta
from typing import Any, TypeVar, Union

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.utils.timezone import now

from pydantic import BaseModel, ConfigDict, Field

from posthog.schema import (
    ActionsNode,
    ActorsQuery,
    CalendarHeatmapQuery,
    DataTableNode,
    DataVisualizationNode,
    DataWarehouseNode,
    EntityType,
    EventsNode,
    EventsQuery,
    FunnelExclusionActionsNode,
    FunnelExclusionEventsNode,
    FunnelsActorsQuery,
    FunnelsDataWarehouseNode,
    FunnelsQuery,
    GroupNode,
    HogQLQuery,
    InsightActorsQuery,
    InsightVizNode,
    LifecycleQuery,
    PathsQuery,
    PathsV2ActorsQuery,
    PathsV2Query,
    PathType,
    RetentionEntity,
    RetentionQuery,
    StickinessActorsQuery,
    StickinessQuery,
    TrendsQuery,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.taxonomy_validation import TaxonomyReferenceVisitor

from posthog.cache_utils import cache_for
from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.utils import get_from_dict_or_attr

from products.actions.backend.models.action import Action

T = TypeVar("T", bound=BaseModel)


class QueryPropertyMetadata(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    # PropertyDefinition-style type: event | person | group | session
    type: str
    name: str
    # Set only for group properties, which are defined per group type.
    group_type_index: int | None = None


class InsightQueryMetadata(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    events: list[str]
    properties: list[QueryPropertyMetadata] = Field(default_factory=list)
    updated_at: datetime


# A single query can reference very many events or properties (wide HogQL selects, long
# `event IN (...)` lists); cap the stored metadata so insight rows stay bounded.
MAX_EVENTS_PER_QUERY_METADATA = 100
MAX_PROPERTIES_PER_QUERY_METADATA = 100

# Property-filter `type` values that map onto a PropertyDefinition type. The rest
# (cohort, hogql, data_warehouse, element, ...) have no definition row to attribute usage to.
PROPERTY_FILTER_TYPE_TO_DEFINITION_TYPE: dict[str, str] = {
    "event": "event",
    "feature": "event",  # $feature/* filters are stored as event-type definitions
    "person": "person",
    "group": "group",
    "session": "session",
}

# math_property_type carries a frontend TaxonomicFilterGroupType value; absent means event property.
MATH_PROPERTY_TYPE_TO_DEFINITION_TYPE: dict[str, str] = {
    "numerical_event_properties": "event",
    "event_properties": "event",
    "session_properties": "session",
    "person_properties": "person",
}


@frozen
class HogQLQueryReferences:
    events: list[str]
    properties: list[str]


class _HogQLReferenceVisitor(TaxonomyReferenceVisitor):
    """Adds `<alias>.properties.<name>` and `<alias>.properties['<name>']` reads to the base visitor.

    The base visitor only knows the unqualified `properties` field. A qualified read counts as an event
    property only when its alias names the events table, because `persons AS p` also has `p.properties`.
    """

    def __init__(self) -> None:
        super().__init__()
        self._events_aliases: set[str] = {"events"}
        self._qualified_reads: list[tuple[str, str]] = []

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        if isinstance(node.table, ast.Field) and node.table.chain == ["events"] and node.alias:
            self._events_aliases.add(node.alias)
        super().visit_join_expr(node)

    def visit_field(self, node: ast.Field) -> None:
        chain = node.chain
        if len(chain) >= 3 and isinstance(chain[0], str) and chain[1] == "properties" and isinstance(chain[2], str):
            self._qualified_reads.append((chain[0], chain[2]))
        super().visit_field(node)

    def visit_array_access(self, node: ast.ArrayAccess) -> None:
        array = node.array
        if (
            isinstance(array, ast.Field)
            and len(array.chain) == 2
            and isinstance(array.chain[0], str)
            and array.chain[1] == "properties"
            and isinstance(node.property, ast.Constant)
            and isinstance(node.property.value, str)
        ):
            self._qualified_reads.append((array.chain[0], node.property.value))
        super().visit_array_access(node)

    def qualified_event_property_names(self) -> list[str]:
        # Aliases resolve after the walk, so the order in which the visitor meets a FROM clause and a read does not matter.
        return [name for alias, name in self._qualified_reads if alias in self._events_aliases]


def _parse_hogql_references(query_str: str) -> HogQLQueryReferences:
    try:
        select = parse_select(query_str)
        visitor = _HogQLReferenceVisitor()
        visitor.visit(select)
    except Exception:
        # Extraction is advisory: an unparseable query contributes no references.
        return HogQLQueryReferences(events=[], properties=[])
    return HogQLQueryReferences(
        events=[reference.name for reference in visitor.event_literals],
        properties=[
            *(reference.name for reference in visitor.property_names),
            *visitor.qualified_event_property_names(),
        ],
    )


class HogQLReferenceExtractor:
    """Parses each HogQL statement once, and gives its references to both metadata extractors.

    `parse_select` does not cache long statements, so without this one metadata extraction parses a
    large SQL insight twice.
    """

    def __init__(self) -> None:
        self._references: dict[str, HogQLQueryReferences] = {}

    def extract(self, query_str: str) -> HogQLQueryReferences:
        if query_str not in self._references:
            self._references[query_str] = _parse_hogql_references(query_str)
        return self._references[query_str]


class QueryEventsExtractor:
    def __init__(self, team: Team, hogql_references: HogQLReferenceExtractor | None = None):
        self.team = team
        self.hogql_references = hogql_references or HogQLReferenceExtractor()

    @staticmethod
    def _ensure_model_instance(query: dict[str, Any] | BaseModel, model_class: type[T]) -> T:
        """
        Ensures the query is an instance of the specified model class.
        """
        if isinstance(query, model_class):
            return query
        return model_class.model_validate(query)

    def extract_events(self, query: dict[str, Any] | BaseModel) -> list[str]:
        """
        Extracts events from a given query dictionary.

        Args:
            query (dict): The query dictionary containing event data.

        Returns:
            list[str]: A list of events
        """
        if not query:
            return []

        try:
            kind = get_from_dict_or_attr(query, "kind")
        except AttributeError:
            raise ValueError(f"unknown query type: {query}")

        events = []

        if kind == "InsightVizNode":
            events = self.extract_events(self._ensure_model_instance(query, InsightVizNode).source)
        elif kind == "DataTableNode":
            events = self.extract_events(self._ensure_model_instance(query, DataTableNode).source)
        elif kind == "DataVisualizationNode":
            events = self.extract_events(self._ensure_model_instance(query, DataVisualizationNode).source)
        elif kind == "ActorsQuery":
            source = self._ensure_model_instance(query, ActorsQuery).source
            events = self.extract_events(source) if source else []
        elif kind == "InsightActorsQuery":
            events = self.extract_events(self._ensure_model_instance(query, InsightActorsQuery).source)
        elif kind == "FunnelsActorsQuery":
            events = self.extract_events(self._ensure_model_instance(query, FunnelsActorsQuery).source)
        elif kind == "StickinessActorsQuery":
            events = self.extract_events(self._ensure_model_instance(query, StickinessActorsQuery).source)
        elif kind == "PathsV2ActorsQuery":
            events = self.extract_events(self._ensure_model_instance(query, PathsV2ActorsQuery).source)

        elif kind == "TrendsQuery":
            events = self._extract_events_from_series(self._ensure_model_instance(query, TrendsQuery).series)
        elif kind == "StickinessQuery":
            events = self._extract_events_from_series(self._ensure_model_instance(query, StickinessQuery).series)
        elif kind == "LifecycleQuery":
            events = self._extract_events_from_series(self._ensure_model_instance(query, LifecycleQuery).series)
        elif kind == "CalendarHeatmapQuery":
            events = self._extract_events_from_series(self._ensure_model_instance(query, CalendarHeatmapQuery).series)

        elif kind == "EventsQuery":
            events = self._extract_events_from_events_query(self._ensure_model_instance(query, EventsQuery))

        elif kind == "FunnelsQuery":
            events = self._extract_events_from_funnels_query(self._ensure_model_instance(query, FunnelsQuery))

        elif kind == "RetentionQuery":
            events = self._extract_events_from_retention_query(self._ensure_model_instance(query, RetentionQuery))

        elif kind == "PathsQuery":
            events = self._extract_events_from_paths_query(self._ensure_model_instance(query, PathsQuery))

        elif kind == "PathsV2Query":
            events = self._extract_events_from_paths_v2_query(self._ensure_model_instance(query, PathsV2Query))

        elif kind == "EventsNode":
            events = self._get_series_events(self._ensure_model_instance(query, EventsNode))

        elif kind == "HogQLQuery":
            events = self.hogql_references.extract(self._ensure_model_instance(query, HogQLQuery).query).events

        return list(set(events))

    def _extract_events_from_series(self, series: list) -> list[str]:
        return [event for series in series for event in self._get_series_events(series)]

    def _extract_events_from_events_query(self, query: EventsQuery) -> list[str]:
        source_events = self.extract_events(query.source) if query.source else []
        return [query.event, *source_events] if query.event else source_events

    def _extract_events_from_funnels_query(self, query: FunnelsQuery) -> list[str]:
        series_events = [event for series in query.series for event in self._get_series_events(series)]

        funnel_filter_events = []
        if query.funnelsFilter and query.funnelsFilter.exclusions:
            for exclusion in query.funnelsFilter.exclusions:
                if isinstance(exclusion, FunnelExclusionEventsNode) and exclusion.event:
                    funnel_filter_events.append(exclusion.event)
                elif isinstance(exclusion, FunnelExclusionActionsNode) and exclusion.id:
                    funnel_filter_events.extend(
                        self._get_action_events(action_id=int(exclusion.id), project_id=self.team.project_id)
                    )

        return list(set(series_events + funnel_filter_events))

    def _extract_events_from_retention_query(self, query: RetentionQuery) -> list[str]:
        target_events = (
            self._get_retention_entity_events(query.retentionFilter.targetEntity)
            if query.retentionFilter.targetEntity
            else []
        )
        returning_events = (
            self._get_retention_entity_events(query.retentionFilter.returningEntity)
            if query.retentionFilter.returningEntity
            else []
        )

        return list(set(target_events + returning_events))

    def _extract_events_from_paths_query(self, query: PathsQuery) -> list[str]:
        included_events = []
        if query.pathsFilter.includeEventTypes and PathType.FIELD_PAGEVIEW in query.pathsFilter.includeEventTypes:
            included_events.append("$pageview")
        if query.pathsFilter.includeEventTypes and PathType.FIELD_SCREEN in query.pathsFilter.includeEventTypes:
            included_events.append("$screen")

        excluded_events = (
            [event for event in query.pathsFilter.excludeEvents if not self._is_valid_url(event)]
            if query.pathsFilter.excludeEvents
            else []
        )

        return list(set(included_events + excluded_events))

    def _extract_events_from_paths_v2_query(self, query: PathsV2Query) -> list[str]:
        if query.pathsV2Filter is None or query.pathsV2Filter.stepSources is None:
            return ["$pageview"]
        return list({source.event for source in query.pathsV2Filter.stepSources})

    @staticmethod
    def _is_valid_url(url: str) -> bool:
        try:
            URLValidator()(url)
            return True
        except ValidationError:
            return False

    def _get_retention_entity_events(self, entity: RetentionEntity) -> list[str]:
        if entity.type == EntityType.EVENTS:
            return [str(entity.id)] if entity.id else []
        elif entity.type == EntityType.ACTIONS:
            return (
                self._get_action_events(action_id=int(entity.id), project_id=self.team.project_id) if entity.id else []
            )

        return []

    def _get_series_events(
        self, series: Union[EventsNode, ActionsNode, DataWarehouseNode, FunnelsDataWarehouseNode, GroupNode]
    ) -> list[str]:
        if isinstance(series, EventsNode):
            return [series.event] if series.event else []
        if isinstance(series, ActionsNode):
            return self._get_action_events(action_id=int(series.id), project_id=self.team.project_id)
        if isinstance(series, GroupNode):
            return [event for value in series.nodes for event in self._get_series_events(value)]

        return []

    @staticmethod
    @cache_for(timedelta(minutes=1))
    def _get_action_events(action_id: int, project_id: int) -> list[str]:
        try:
            action = Action.objects.get(pk=action_id, team__project_id=project_id)
            return [event for event in action.get_step_events() if event is not None]
        except Action.DoesNotExist:
            return []


# (definition type, group type index or -1, name). The index takes -1 rather than None so the keys sort.
_PropertyKey = tuple[str, int, str]


class QueryPropertiesExtractor:
    """Collects property references from a query as PropertyDefinition-style (type, group type index, name).

    Walks the query JSON generically instead of dispatching per query kind: property filters
    are uniform `{key, type}` dicts wherever they appear (series, global filters, funnel
    exclusions, actors queries), so a recursive walk covers every kind at once.
    """

    def __init__(self, team: Team, hogql_references: HogQLReferenceExtractor | None = None):
        self.team = team
        self.hogql_references = hogql_references or HogQLReferenceExtractor()

    def extract_properties(self, query: dict[str, Any] | BaseModel | None) -> list[QueryPropertyMetadata]:
        if not query:
            return []
        data = query.model_dump(exclude_none=True) if isinstance(query, BaseModel) else query
        found: dict[_PropertyKey, QueryPropertyMetadata] = {}
        self._walk(data, found)
        return [found[key] for key in sorted(found)][:MAX_PROPERTIES_PER_QUERY_METADATA]

    def _walk(self, node: Any, found: dict[_PropertyKey, QueryPropertyMetadata]) -> None:
        if isinstance(node, list):
            for item in node:
                self._walk(item, found)
            return
        if not isinstance(node, dict):
            return
        self._collect_property_filter(node, found)
        self._collect_breakdowns(node, found)
        self._collect_math_property(node, found)
        self._collect_hogql_properties(node, found)
        self._collect_action_step_properties(node, found)
        for value in node.values():
            self._walk(value, found)

    def _collect_property_filter(self, node: dict, found: dict[_PropertyKey, QueryPropertyMetadata]) -> None:
        key = node.get("key")
        filter_type = node.get("type")
        if not isinstance(key, str) or not key or not isinstance(filter_type, str):
            return
        definition_type = PROPERTY_FILTER_TYPE_TO_DEFINITION_TYPE.get(filter_type)
        if definition_type:
            self._add(found, definition_type, key, node.get("group_type_index"))

    def _collect_breakdowns(self, node: dict, found: dict[_PropertyKey, QueryPropertyMetadata]) -> None:
        breakdowns = node.get("breakdowns")
        if isinstance(breakdowns, list):
            for entry in breakdowns:
                if not isinstance(entry, dict):
                    continue
                breakdown_property = entry.get("property")
                entry_type = entry.get("type") or "event"
                if not isinstance(breakdown_property, str) or not breakdown_property or not isinstance(entry_type, str):
                    continue
                definition_type = PROPERTY_FILTER_TYPE_TO_DEFINITION_TYPE.get(entry_type)
                if definition_type:
                    self._add(found, definition_type, breakdown_property, entry.get("group_type_index"))

        breakdown = node.get("breakdown")
        if breakdown is None:
            return
        breakdown_type = node.get("breakdown_type") or "event"
        if not isinstance(breakdown_type, str):
            return
        definition_type = PROPERTY_FILTER_TYPE_TO_DEFINITION_TYPE.get(breakdown_type)
        if not definition_type:
            return
        values = breakdown if isinstance(breakdown, list) else [breakdown]
        for value in values:
            if isinstance(value, str) and value:
                self._add(found, definition_type, value, node.get("breakdown_group_type_index"))

    def _collect_math_property(self, node: dict, found: dict[_PropertyKey, QueryPropertyMetadata]) -> None:
        math_property = node.get("math_property")
        if not isinstance(math_property, str) or not math_property:
            return
        # Trends aggregation treats `$session_duration` as a session property whatever the type says,
        # because older insights store it without a math_property_type.
        if math_property == "$session_duration":
            self._add(found, "session", math_property)
            return
        math_property_type = node.get("math_property_type") or "numerical_event_properties"
        if not isinstance(math_property_type, str):
            return
        definition_type = MATH_PROPERTY_TYPE_TO_DEFINITION_TYPE.get(math_property_type)
        if definition_type:
            self._add(found, definition_type, math_property)

    def _collect_hogql_properties(self, node: dict, found: dict[_PropertyKey, QueryPropertyMetadata]) -> None:
        if node.get("kind") != "HogQLQuery":
            return
        hogql = node.get("query")
        if not isinstance(hogql, str) or not hogql.strip():
            return
        # The visitor is context-free, so `properties.x` is attributed to events; person/group
        # property accesses in HogQL are not collected.
        for name in self.hogql_references.extract(hogql).properties:
            self._add(found, "event", name)

    def _collect_action_step_properties(self, node: dict, found: dict[_PropertyKey, QueryPropertyMetadata]) -> None:
        # Series and funnel exclusions name an action by `kind`; retention entities name it by `type`.
        if node.get("kind") not in ("ActionsNode", "FunnelExclusionActionsNode") and node.get("type") != "actions":
            return
        try:
            action_id = int(node["id"])
        except (KeyError, TypeError, ValueError):
            return
        for step_properties in _get_action_step_properties(action_id=action_id, project_id=self.team.project_id):
            self._walk(step_properties, found)

    @staticmethod
    def _add(
        found: dict[_PropertyKey, QueryPropertyMetadata],
        definition_type: str,
        name: str,
        group_type_index: Any = None,
    ) -> None:
        if definition_type != "group":
            found.setdefault((definition_type, -1, name), QueryPropertyMetadata(type=definition_type, name=name))
            return
        # Each group type has its own definitions, so a group reference without a valid index has no row to count.
        if not isinstance(group_type_index, int) or isinstance(group_type_index, bool) or group_type_index < 0:
            return
        found.setdefault(
            (definition_type, group_type_index, name),
            QueryPropertyMetadata(type=definition_type, name=name, group_type_index=group_type_index),
        )


@cache_for(timedelta(minutes=1))
def _get_action_step_properties(action_id: int, project_id: int) -> list[list[dict]]:
    try:
        action = Action.objects.get(pk=action_id, team__project_id=project_id)
    except Action.DoesNotExist:
        return []
    return [step.properties for step in action.steps if step.properties]


def extract_query_metadata(
    query: dict[str, Any] | BaseModel | None,
    team: Team,
) -> InsightQueryMetadata:
    """
    Extracts metadata from a given query: the events and the properties it references.

    Args:
        query (dict) | BaseModel | None: The query to extract metadata from. If None, returns an empty metadata object.
        team (Team): The team associated with the query.

    Returns:
        InsightQueryMetadata: An object containing the query metadata
    """
    if not query:
        return InsightQueryMetadata(events=[], properties=[], updated_at=now())

    hogql_references = HogQLReferenceExtractor()
    events_extractor = QueryEventsExtractor(team=team, hogql_references=hogql_references)
    events = sorted(events_extractor.extract_events(query=query))[:MAX_EVENTS_PER_QUERY_METADATA]
    properties = QueryPropertiesExtractor(team=team, hogql_references=hogql_references).extract_properties(query=query)

    return InsightQueryMetadata(events=events, properties=properties, updated_at=now())
