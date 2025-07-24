from datetime import timedelta, datetime
from typing import Any, Union, TypeVar

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from pydantic import BaseModel

from posthog.cache_utils import cache_for
from posthog.models import Action, Team
from posthog.schema import (
    TrendsQuery,
    InsightVizNode,
    EventsNode,
    ActionsNode,
    DataWarehouseNode,
    FunnelsQuery,
    RetentionQuery,
    EntityType,
    RetentionEntity,
    PathsQuery,
    PathType,
    StickinessQuery,
    LifecycleQuery,
    CalendarHeatmapQuery,
    DataTableNode,
    ActorsQuery,
    InsightActorsQuery,
    FunnelsActorsQuery,
    FunnelCorrelationActorsQuery,
    StickinessActorsQuery,
    FunnelCorrelationQuery,
    EventsQuery,
    InsightQueryMetadata,
)
from posthog.utils import get_from_dict_or_attr
from posthog.hogql_queries.query_runner import RunnableQueryNode

T = TypeVar("T", bound=BaseModel)


class QueryEventsExtractor:
    def __init__(self, team: Team):
        self.team = team

    @staticmethod
    def _ensure_model_instance(query: dict[str, Any] | RunnableQueryNode | BaseModel, model_class: type[T]) -> T:
        """
        Ensures the query is an instance of the specified model class.
        """
        if isinstance(query, model_class):
            return query
        return model_class.model_validate(query)

    def extract_events(self, query: dict[str, Any] | RunnableQueryNode | BaseModel) -> list[str]:
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
        elif kind == "ActorsQuery":
            source = self._ensure_model_instance(query, ActorsQuery).source
            events = self.extract_events(source) if source else []
        elif kind == "InsightActorsQuery":
            events = self.extract_events(self._ensure_model_instance(query, InsightActorsQuery).source)
        elif kind == "FunnelsActorsQuery":
            events = self.extract_events(self._ensure_model_instance(query, FunnelsActorsQuery).source)
        elif kind == "FunnelCorrelationActorsQuery":
            events = self.extract_events(self._ensure_model_instance(query, FunnelCorrelationActorsQuery).source)
        elif kind == "StickinessActorsQuery":
            events = self.extract_events(self._ensure_model_instance(query, StickinessActorsQuery).source)

        elif kind == "TrendsQuery":
            events = self._extract_events_from_series(self._ensure_model_instance(query, TrendsQuery).series)
        elif kind == "StickinessQuery":
            events = self._extract_events_from_series(self._ensure_model_instance(query, StickinessQuery).series)
        elif kind == "LifecycleQuery":
            events = self._extract_events_from_series(self._ensure_model_instance(query, LifecycleQuery).series)
        elif kind == "CalendarHeatmapQuery":
            events = self._extract_events_from_series(self._ensure_model_instance(query, CalendarHeatmapQuery).series)

        elif kind == "FunnelCorrelationQuery":
            events = self._extract_events_from_funnels_correlation_query(
                self._ensure_model_instance(query, FunnelCorrelationQuery)
            )

        elif kind == "EventsQuery":
            events = self._extract_events_from_events_query(self._ensure_model_instance(query, EventsQuery))

        elif kind == "FunnelsQuery":
            events = self._extract_events_from_funnels_query(self._ensure_model_instance(query, FunnelsQuery))

        elif kind == "RetentionQuery":
            events = self._extract_events_from_retention_query(self._ensure_model_instance(query, RetentionQuery))

        elif kind == "PathsQuery":
            events = self._extract_events_from_paths_query(self._ensure_model_instance(query, PathsQuery))

        elif kind == "EventsNode":
            events = self._get_series_events(self._ensure_model_instance(query, EventsNode))

        return list(set(events))

    def _extract_events_from_series(self, series: list) -> list[str]:
        return [event for series in series for event in self._get_series_events(series)]

    def _extract_events_from_events_query(self, query: EventsQuery) -> list[str]:
        source_events = self.extract_events(query.source) if query.source else []
        return [query.event, *source_events] if query.event else source_events

    def _extract_events_from_funnels_query(self, query: FunnelsQuery) -> list[str]:
        series_events = [event for series in query.series for event in self._get_series_events(series)]
        funnel_filter_events = (
            [_.event for _ in query.funnelsFilter.exclusions]
            if query.funnelsFilter and query.funnelsFilter.exclusions
            else []
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
            included_events.append(str(PathType.FIELD_PAGEVIEW))
        if query.pathsFilter.includeEventTypes and PathType.FIELD_SCREEN in query.pathsFilter.includeEventTypes:
            included_events.append(str(PathType.FIELD_SCREEN))

        excluded_events = (
            [event for event in query.pathsFilter.excludeEvents if not self._is_valid_url(event)]
            if query.pathsFilter.excludeEvents
            else []
        )

        return list(set(included_events + excluded_events))

    def _extract_events_from_funnels_correlation_query(self, query: FunnelCorrelationQuery) -> list[str]:
        events = self.extract_events(query.source)

        if query.funnelCorrelationEventNames:
            events.extend(query.funnelCorrelationEventNames)

        if query.funnelCorrelationExcludeEventNames:
            events.extend(query.funnelCorrelationExcludeEventNames)

        return list(set(events))

    @staticmethod
    def _is_valid_url(url: str) -> bool:
        try:
            URLValidator()(url)
            return True
        except ValidationError:
            return False

    def _get_retention_entity_events(self, entity: RetentionEntity) -> list[str]:
        if entity.type == EntityType.EVENTS:
            return [entity.id] if entity.id else []
        elif entity.type == EntityType.ACTIONS:
            return (
                self._get_action_events(action_id=int(entity.id), project_id=self.team.project_id) if entity.id else []
            )

        return []

    def _get_series_events(self, series: Union[EventsNode, ActionsNode, DataWarehouseNode]) -> list[str]:
        if isinstance(series, EventsNode):
            return [series.event] if series.event else []
        if isinstance(series, ActionsNode):
            return self._get_action_events(action_id=int(series.id), project_id=self.team.project_id)

        return []

    @staticmethod
    @cache_for(timedelta(minutes=1))
    def _get_action_events(action_id: int, project_id: int) -> list[str]:
        action = Action.objects.get(pk=action_id, team__project_id=project_id)
        step_events = action.get_step_events()
        return step_events if step_events else []


def extract_query_metadata(
    query: dict[str, Any] | RunnableQueryNode | BaseModel,
    team: Team,
) -> InsightQueryMetadata:
    """
    Extracts metadata from a given query, including the events used in the query.

    Args:
        query (dict | RunnableQueryNode | BaseModel): The query to extract metadata from.
        team (Team): The team associated with the query.

    Returns:
        InsightQueryMetadata: An object containing the query metadata
    """
    events_extractor = QueryEventsExtractor(team=team)
    events = events_extractor.extract_events(query=query)

    return InsightQueryMetadata(events=events, updated_at=datetime.now())
