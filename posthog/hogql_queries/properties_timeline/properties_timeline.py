import json
import datetime
from typing import Any, TypedDict, Union

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

from posthog.dataclasses import frozen
from posthog.models.group.group import Group
from posthog.models.person.person import Person
from posthog.models.property.util import count_hogql_properties
from posthog.models.team.team import Team

from products.actions.backend.models.action import Action
from products.product_analytics.backend.facade import queries as product_analytics_queries


@frozen
class _TimelineScope:
    """The actor's events that the timeline reads, and the properties whose changes it tracks."""

    series_expr: ast.Expr | None
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
    def _actor_properties_chain(self, aggregation_group_type_index: int | None) -> list[Union[str, int]]:
        # Read the actor's properties as frozen on the event (persons-on-events columns), so the
        # timeline reflects the values at the time of each event rather than current values.
        if aggregation_group_type_index is None:
            return ["poe", "properties"]
        return [f"goe_{aggregation_group_type_index}", "properties"]

    def _series_expr(self, series: EventsNode | ActionsNode, team: Team) -> ast.Expr | None:
        # Only the series' event or action selects events. Its property filters name key properties,
        # and filtering on them would hide the changes the timeline shows.
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
        return _TimelineScope(
            series_expr=self._series_expr(series, team),
            crucial_property_keys=tuple(sorted(crucial_property_keys)),
            aggregation_group_type_index=aggregation_group_type_index,
            date_from=window.date_from.astimezone(team.timezone_info),
            date_to=window.date_to.astimezone(team.timezone_info),
            date_to_inclusive=window.date_to_inclusive,
        )

    def run(self, query: InsightActorsQuery, team: Team, actor: Union[Person, Group]) -> PropertiesTimelineResult:
        """The actor's key property values over the window of the Trends data point that `query` selects."""
        return self._run(self._scope_from_query(query, team), team, actor)

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
        if scope.series_expr is not None:
            where_exprs.append(scope.series_expr)

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
