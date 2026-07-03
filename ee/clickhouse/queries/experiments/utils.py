import json
from typing import Union

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.filters.filter import Filter
from posthog.models.team.team import Team


def _has_feature_flag_property(properties: object) -> bool:
    if isinstance(properties, str):
        raw_properties = properties
        try:
            properties = json.loads(raw_properties)
        except json.JSONDecodeError:
            return "$feature/" in raw_properties.replace("\\/", "/")

    return isinstance(properties, dict) and any(key.startswith("$feature/") for key in properties)


def requires_flag_warning(filter: Filter, team: Team) -> bool:
    events: set[Union[int, str]] = set()

    for entity in filter.entities:
        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = entity.get_action(team.pk)
            for step_event in action.get_step_events():
                if step_event:
                    # TODO: Fix this to detect if "all events" (i.e. None) is in the list and change the entity query to e.g. AND 1=1
                    events.add(step_event)
        elif entity.id is not None:
            events.add(entity.id)

    query = parse_select(
        """
        SELECT event, groupArraySample({limit})(properties)
        FROM events
        WHERE event IN {events}
            AND timestamp >= {date_from}
            AND timestamp <= {date_to}
        GROUP BY event
        """,
        placeholders={
            "limit": ast.Constant(value=filter.limit or 20),
            "events": ast.Constant(value=sorted(events)),
            "date_from": ast.Constant(value=filter.date_from),
            "date_to": ast.Constant(value=filter.date_to),
        },
    )
    response = execute_hogql_query(query, team=team)

    for _event, property_group_list in response.results:
        for property_group in property_group_list:
            if _has_feature_flag_property(property_group):
                return False

    return True
