import json
import datetime
from datetime import timedelta
from typing import Any, TypedDict, Union, cast
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

from posthog.schema import (
    ActionsNode,
    BreakdownFilter,
    EventsNode,
    GroupPropertyFilter,
    HogQLPropertyFilter,
    HogQLQueryModifiers,
    InsightActorsQuery,
    PersonPropertyFilter,
    PersonsOnEventsMode,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    TrendsQuery,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import action_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.constants import NON_TIME_SERIES_DISPLAY_TYPES, TREND_FILTER_TYPE_ACTIONS
from posthog.dataclasses import frozen
from posthog.hogql_queries.properties_timeline.query_date_range import QueryDateRange
from posthog.models.entity import Entity
from posthog.models.filters.properties_timeline_filter import PropertiesTimelineFilter
from posthog.models.group.group import Group
from posthog.models.person.person import Person
from posthog.models.property.util import count_hogql_properties, extract_tables_and_properties
from posthog.models.team.team import Team

from products.actions.backend.models.action import Action
from products.product_analytics.backend.facade import queries as product_analytics_queries


def offset_time_series_date_by_interval(
    date: datetime.datetime, *, filter: PropertiesTimelineFilter, team: Team
) -> datetime.datetime:
    """If the insight is time-series, offset date according to the interval of the filter."""
    if filter.display in NON_TIME_SERIES_DISPLAY_TYPES:
        return date
    if filter.interval == "month":
        date = (date + relativedelta(months=1) - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    elif filter.interval == "week":
        date = (date + timedelta(weeks=1) - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    elif filter.interval == "hour":
        date = date + timedelta(hours=1)
    else:  # "day" is the default interval
        date = date.replace(hour=23, minute=59, second=59, microsecond=999999)
    if date.tzinfo is None:
        date = date.replace(tzinfo=ZoneInfo(team.timezone))
    return date


@frozen
class _TimelineScope:
    """The actor's events that the timeline reads, and the properties whose changes it tracks."""

    entity_exprs: tuple[ast.Expr, ...]
    crucial_property_keys: tuple[str, ...]
    aggregation_group_type_index: int | None
    date_from: datetime.datetime
    date_to: datetime.datetime
    date_to_inclusive: bool


def _crucial_keys_in_hogql(expression: str, aggregation_group_type_index: int | None) -> set[str]:
    if aggregation_group_type_index is not None:
        return set()
    return {key for key, property_type, _ in count_hogql_properties(expression) if property_type == "person"}


def _crucial_keys_in_properties(properties: object, aggregation_group_type_index: int | None) -> set[str]:
    """Keys of the aggregated actor's properties that a property filter list or group uses."""
    match properties:
        case list():
            return set().union(
                *(_crucial_keys_in_properties(item, aggregation_group_type_index) for item in properties)
            )
        case PropertyGroupFilter() | PropertyGroupFilterValue():
            return _crucial_keys_in_properties(properties.values, aggregation_group_type_index)
        case PersonPropertyFilter(key=key) if aggregation_group_type_index is None:
            return {key}
        case GroupPropertyFilter(key=key, group_type_index=group_type_index) if (
            group_type_index is not None and group_type_index == aggregation_group_type_index
        ):
            return {key}
        case HogQLPropertyFilter(key=expression):
            return _crucial_keys_in_hogql(expression, aggregation_group_type_index)
        case _:
            return set()


def _crucial_keys_in_breakdown(
    breakdown_type: str | None,
    breakdown_properties: list[str | int],
    breakdown_group_type_index: int | None,
    aggregation_group_type_index: int | None,
) -> set[str]:
    if breakdown_type == "person" and aggregation_group_type_index is None:
        return {str(breakdown_property) for breakdown_property in breakdown_properties}
    if (
        breakdown_type == "group"
        and breakdown_group_type_index is not None
        and breakdown_group_type_index == aggregation_group_type_index
    ):
        return {str(breakdown_property) for breakdown_property in breakdown_properties}
    if breakdown_type == "hogql":
        return set().union(
            *(
                _crucial_keys_in_hogql(str(expression), aggregation_group_type_index)
                for expression in breakdown_properties
            )
        )
    return set()


def _crucial_keys_in_breakdown_filter(
    breakdown_filter: BreakdownFilter | None, aggregation_group_type_index: int | None
) -> set[str]:
    if breakdown_filter is None:
        return set()
    keys: set[str] = set()
    if breakdown_filter.breakdown is not None:
        keys |= _crucial_keys_in_breakdown(
            breakdown_filter.breakdown_type,
            breakdown_filter.breakdown
            if isinstance(breakdown_filter.breakdown, list)
            else [breakdown_filter.breakdown],
            breakdown_filter.breakdown_group_type_index,
            aggregation_group_type_index,
        )
    for breakdown in breakdown_filter.breakdowns or []:
        keys |= _crucial_keys_in_breakdown(
            breakdown.type, [breakdown.property], breakdown.group_type_index, aggregation_group_type_index
        )
    return keys


class PropertiesTimelinePoint(TypedDict):
    timestamp: str
    properties: dict[str, Any]
    relevant_event_count: int


class PropertiesTimelineResult(TypedDict):
    points: list[PropertiesTimelinePoint]
    crucial_property_keys: list[str]
    effective_date_from: str
    effective_date_to: str


# relevant_event_count of each point is the number of events between consecutive changes of the
# crucial property values. We detect changes with lagInFrame over the ordered event stream, keep only
# the change points, then use leadInFrame (defaulting to total_events + 1 for the last segment) to
# measure how many events each segment spans — equivalent to the legacy UNION-ALL sentinel-row trick.
PROPERTIES_TIMELINE_HOGQL = """
SELECT
    timestamp,
    properties,
    end_event_number - start_event_number AS relevant_event_count
FROM (
    SELECT
        timestamp,
        properties,
        start_event_number,
        leadInFrame(start_event_number, 1, total_events + 1) OVER (
            ORDER BY timestamp ASC ROWS BETWEEN CURRENT ROW AND 1 FOLLOWING
        ) AS end_event_number
    FROM (
        SELECT
            timestamp,
            {actor_properties} AS properties,
            {crucial_properties} AS relevant_property_values,
            lagInFrame({crucial_properties}) OVER (
                ORDER BY timestamp ASC ROWS BETWEEN 1 PRECEDING AND CURRENT ROW
            ) AS previous_relevant_property_values,
            row_number() OVER (
                ORDER BY timestamp ASC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS start_event_number,
            count() OVER () AS total_events
        FROM events
        WHERE {where}
    )
    WHERE start_event_number = 1 OR relevant_property_values != previous_relevant_property_values
)
ORDER BY timestamp ASC
"""


class PropertiesTimeline:
    def extract_crucial_property_keys(self, filter: PropertiesTimelineFilter, team_id: int) -> set[str]:
        is_filter_relevant = lambda property_type, property_group_type_index: (
            (property_type == "person")
            if filter.aggregation_group_type_index is None
            else (property_type == "group" and property_group_type_index == filter.aggregation_group_type_index)
        )

        property_filters = list(filter.property_groups.flat)
        for event in filter.entities:
            property_filters.extend(event.property_groups.flat)
        all_property_identifiers = extract_tables_and_properties(property_filters, team_id=team_id)

        crucial_property_keys = {
            property_key
            for property_key, property_type, property_group_type_index in all_property_identifiers
            if is_filter_relevant(property_type, property_group_type_index)
        }

        if filter.breakdown and filter.breakdown_type == "person":
            if isinstance(filter.breakdown, list):
                crucial_property_keys.update(cast(list[str], filter.breakdown))
            else:
                crucial_property_keys.add(filter.breakdown)

        return crucial_property_keys

    def _actor_properties_chain(self, aggregation_group_type_index: int | None) -> list[Union[str, int]]:
        # Read the actor's properties as frozen on the event (persons-on-events columns), so the
        # timeline reflects the values at the time of each event rather than current values.
        if aggregation_group_type_index is None:
            return ["poe", "properties"]
        return [f"goe_{aggregation_group_type_index}", "properties"]

    def _entity_expr(self, entity: Entity, team: Team) -> ast.Expr:
        # Only the entity's event/action identity filters the timeline events — the entity's ad-hoc
        # property filters are not applied here (they only feed crucial-property-key extraction), matching
        # the legacy behavior.
        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = Action.objects.get(pk=cast(Union[int, str], entity.id), team=team)
            return action_to_expr(action)
        return ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["event"]),
            right=ast.Constant(value=entity.id),
        )

    def _series_expr(self, series: EventsNode | ActionsNode, team: Team) -> ast.Expr | None:
        # Like `_entity_expr`, only the series' event or action selects events. Its property filters
        # name key properties, and filtering on them would hide the changes the timeline shows.
        if isinstance(series, ActionsNode):
            action = Action.objects.filter(pk=series.id, team__project_id=team.project_id).first()
            return action_to_expr(action) if action is not None else ast.Constant(value=False)
        if series.event is None:
            return None
        return ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["event"]),
            right=ast.Constant(value=series.event),
        )

    def _scope_from_filter(self, filter: PropertiesTimelineFilter, team: Team) -> _TimelineScope:
        if filter._date_from is not None and filter._date_to is not None and filter._date_from == filter._date_to:
            # A single-point range is widened by one interval so the window actually spans some events.
            filter = filter.shallow_clone(
                {
                    "date_to": offset_time_series_date_by_interval(
                        cast(datetime.datetime, filter.date_from),
                        filter=filter,
                        team=team,
                    )
                }
            )

        query_date_range = QueryDateRange(filter, team)
        return _TimelineScope(
            entity_exprs=tuple(self._entity_expr(entity, team) for entity in filter.entities),
            crucial_property_keys=tuple(sorted(self.extract_crucial_property_keys(filter, team_id=team.pk))),
            aggregation_group_type_index=filter.aggregation_group_type_index,
            date_from=query_date_range.date_from_param.replace(tzinfo=team.timezone_info),
            date_to=query_date_range.date_to_param.replace(tzinfo=team.timezone_info),
            date_to_inclusive=True,
        )

    def _scope_from_query(self, query: InsightActorsQuery, team: Team) -> _TimelineScope:
        source = query.source
        if not isinstance(source, TrendsQuery):
            raise ValueError(f"The properties timeline does not support {source.kind} insights")
        series = source.series[query.series or 0]
        if not isinstance(series, EventsNode | ActionsNode):
            raise ValueError(f"The properties timeline does not support {series.kind} series")

        aggregation_group_type_index = source.aggregation_group_type_index
        crucial_property_keys = (
            _crucial_keys_in_properties(series.properties, aggregation_group_type_index)
            | _crucial_keys_in_properties(source.properties, aggregation_group_type_index)
            | _crucial_keys_in_breakdown_filter(source.breakdownFilter, aggregation_group_type_index)
        )
        # The facade imports the trends runner on first attribute access, which keeps it off the startup import path.
        window = product_analytics_queries.trends_actors_date_window(team=team, query=query)
        series_expr = self._series_expr(series, team)
        return _TimelineScope(
            entity_exprs=(series_expr,) if series_expr is not None else (),
            crucial_property_keys=tuple(sorted(crucial_property_keys)),
            aggregation_group_type_index=aggregation_group_type_index,
            date_from=window.date_from.astimezone(team.timezone_info),
            date_to=window.date_to.astimezone(team.timezone_info),
            date_to_inclusive=window.date_to_inclusive,
        )

    def run(self, query: InsightActorsQuery, team: Team, actor: Union[Person, Group]) -> PropertiesTimelineResult:
        """The actor's key property values over the window of the Trends data point that `query` selects."""
        return self._run(self._scope_from_query(query, team), team, actor)

    def run_for_filter(
        self, filter: PropertiesTimelineFilter, team: Team, actor: Union[Person, Group]
    ) -> PropertiesTimelineResult:
        return self._run(self._scope_from_filter(filter, team), team, actor)

    def _run(self, scope: _TimelineScope, team: Team, actor: Union[Person, Group]) -> PropertiesTimelineResult:
        actor_properties_chain = self._actor_properties_chain(scope.aggregation_group_type_index)
        # Serialize the crucial property values to a single string for change detection. A tuple would
        # break `lagInFrame`, whose out-of-frame default is an empty tuple that ClickHouse refuses to
        # compare against a sized tuple.
        crucial_properties: ast.Expr
        if scope.crucial_property_keys:
            crucial_properties = ast.Call(
                name="toString",
                args=[
                    ast.Tuple(
                        exprs=[ast.Field(chain=[*actor_properties_chain, key]) for key in scope.crucial_property_keys]
                    )
                ],
            )
        else:
            crucial_properties = ast.Constant(value="")

        where_exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["poe", "id"]),
                right=ast.Constant(value=actor.uuid if isinstance(actor, Person) else actor.group_key),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=scope.date_from),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq if scope.date_to_inclusive else ast.CompareOperationOp.Lt,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=scope.date_to),
            ),
        ]
        if scope.entity_exprs:
            where_exprs.append(
                ast.Or(exprs=list(scope.entity_exprs)) if len(scope.entity_exprs) > 1 else scope.entity_exprs[0]
            )

        query = parse_select(
            PROPERTIES_TIMELINE_HOGQL,
            placeholders={
                "actor_properties": ast.Field(chain=actor_properties_chain),
                "crucial_properties": crucial_properties,
                "where": ast.And(exprs=where_exprs),
            },
        )

        response = execute_hogql_query(
            query,
            team=team,
            query_type="properties_timeline",
            modifiers=HogQLQueryModifiers(
                personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS
            ),
        )

        return PropertiesTimelineResult(
            points=[
                PropertiesTimelinePoint(
                    # Returned as a datetime so DRF renders it with a "Z" suffix, matching the legacy shape.
                    timestamp=timestamp,
                    properties=properties if isinstance(properties, dict) else json.loads(properties),
                    relevant_event_count=relevant_event_count,
                )
                for timestamp, properties, relevant_event_count in response.results
            ],
            crucial_property_keys=list(scope.crucial_property_keys),
            effective_date_from=scope.date_from.isoformat(),
            effective_date_to=scope.date_to.isoformat(),
        )
