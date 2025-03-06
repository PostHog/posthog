from typing import Union

from posthog.clickhouse.client import sync_execute
from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.filters.filter import Filter
from posthog.models.team.team import Team
from posthog.queries.query_date_range import QueryDateRange


def requires_flag_warning(filter: Filter, team: Team) -> bool:
    date_params = {}
    query_date_range = QueryDateRange(filter=filter, team=team, should_round=False)
    parsed_date_from, date_from_params = query_date_range.date_from
    parsed_date_to, date_to_params = query_date_range.date_to
    date_params.update(date_from_params)
    date_params.update(date_to_params)

    date_query = f"""
    {parsed_date_from}
    {parsed_date_to}
    """

    events: set[Union[int, str]] = set()
    entities_to_use = filter.entities

    for entity in entities_to_use:
        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = entity.get_action()
            for step_event in action.get_step_events():
                if step_event:
                    # TODO: Fix this to detect if "all events" (i.e. None) is in the list and change the entiry query to e.g. AND 1=1
                    events.add(step_event)
        elif entity.id is not None:
            events.add(entity.id)

    entity_query = f"AND event IN %(events_list)s"
    entity_params = {"events_list": sorted(events)}

    events_result = sync_execute(
        f"""
        SELECT
            event,
            groupArraySample(%(limit)s)(properties)
        FROM events
        WHERE
        team_id = %(team_id)s
        {entity_query}
        {date_query}
        GROUP BY event
        """,
        {
            "team_id": team.pk,
            "limit": filter.limit or 20,
            **date_params,
            **entity_params,
            **filter.hogql_context.values,
        },
    )

    requires_flag_warning = True

    for _event, property_group_list in events_result:
        for property_group in property_group_list:
            if "$feature/" in property_group:
                requires_flag_warning = False
                break

    return requires_flag_warning
