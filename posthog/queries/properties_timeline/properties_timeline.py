import json
import datetime
from typing import Any, TypedDict, Union, cast

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import action_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.entity import Entity
from posthog.models.filters.properties_timeline_filter import PropertiesTimelineFilter
from posthog.models.group.group import Group
from posthog.models.person.person import Person
from posthog.models.property.util import extract_tables_and_properties
from posthog.models.team.team import Team
from posthog.queries.query_date_range import QueryDateRange
from posthog.queries.trends.util import offset_time_series_date_by_interval

from products.actions.backend.models.action import Action


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

        property_filters = filter.property_groups.flat
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

    def _actor_properties_chain(self, filter: PropertiesTimelineFilter) -> list[Union[str, int]]:
        # Read the actor's properties as frozen on the event (persons-on-events columns), so the
        # timeline reflects the values at the time of each event rather than current values.
        if filter.aggregation_group_type_index is None:
            return ["poe", "properties"]
        return [f"goe_{filter.aggregation_group_type_index}", "properties"]

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

    def run(
        self, filter: PropertiesTimelineFilter, team: Team, actor: Union[Person, Group]
    ) -> PropertiesTimelineResult:
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
        effective_date_from = query_date_range.date_from_param.replace(tzinfo=team.timezone_info)
        effective_date_to = query_date_range.date_to_param.replace(tzinfo=team.timezone_info)

        crucial_property_keys = sorted(self.extract_crucial_property_keys(filter, team_id=team.pk))
        actor_properties_chain = self._actor_properties_chain(filter)
        # Serialize the crucial property values to a single string for change detection. A tuple would
        # break `lagInFrame`, whose out-of-frame default is an empty tuple that ClickHouse refuses to
        # compare against a sized tuple.
        crucial_properties: ast.Expr
        if crucial_property_keys:
            crucial_properties = ast.Call(
                name="toString",
                args=[
                    ast.Tuple(exprs=[ast.Field(chain=[*actor_properties_chain, key]) for key in crucial_property_keys])
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
                right=ast.Constant(value=effective_date_from),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=effective_date_to),
            ),
        ]
        entity_exprs = [self._entity_expr(entity, team) for entity in filter.entities]
        if entity_exprs:
            where_exprs.append(ast.Or(exprs=entity_exprs) if len(entity_exprs) > 1 else entity_exprs[0])

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
            crucial_property_keys=crucial_property_keys,
            effective_date_from=effective_date_from.isoformat(),
            effective_date_to=effective_date_to.isoformat(),
        )
