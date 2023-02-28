from datetime import timedelta
from typing import Dict, List, Optional, Tuple, Union

from dateutil.parser import isoparse
from django.utils.timezone import now

from posthog.api.utils import get_pk_or_uuid
from posthog.clickhouse.client.connection import Workload
from posthog.hogql.context import HogQLContext
from posthog.models import Action, Filter, Person, Team
from posthog.models.action.util import format_action_filter
from posthog.models.event.events_query import QUERY_DEFAULT_LIMIT
from posthog.models.event.sql import (
    SELECT_EVENT_BY_TEAM_AND_CONDITIONS_FILTERS_SQL,
    SELECT_EVENT_BY_TEAM_AND_CONDITIONS_SQL,
)
from posthog.models.property.util import parse_prop_grouped_clauses
from posthog.queries.insight import insight_query_with_columns
from posthog.utils import relative_date_parse


def determine_event_conditions(conditions: Dict[str, Union[None, str, List[str]]]) -> Tuple[str, Dict]:
    result = ""
    params: Dict[str, Union[str, List[str]]] = {}
    for (k, v) in conditions.items():
        if not isinstance(v, str):
            continue
        if k == "after":
            try:
                timestamp = isoparse(v).strftime("%Y-%m-%d %H:%M:%S.%f")
            except ValueError:
                timestamp = relative_date_parse(v).strftime("%Y-%m-%d %H:%M:%S.%f")
            result += "AND timestamp > %(after)s "
            params.update({"after": timestamp})
        elif k == "before":
            try:
                timestamp = isoparse(v).strftime("%Y-%m-%d %H:%M:%S.%f")
            except ValueError:
                timestamp = relative_date_parse(v).strftime("%Y-%m-%d %H:%M:%S.%f")
            result += "AND timestamp < %(before)s "
            params.update({"before": timestamp})
        elif k == "person_id":
            result += """AND distinct_id IN (%(distinct_ids)s) """
            person = get_pk_or_uuid(Person.objects.all(), v).first()
            distinct_ids = person.distinct_ids if person is not None else []
            params.update({"distinct_ids": list(map(str, distinct_ids))})
        elif k == "distinct_id":
            result += "AND distinct_id = %(distinct_id)s "
            params.update({"distinct_id": v})
        elif k == "event":
            result += "AND event = %(event)s "
            params.update({"event": v})
    return result, params


def query_events_list(
    filter: Filter,
    team: Team,
    request_get_query_dict: Dict,
    order_by: List[str],
    action_id: Optional[str],
    unbounded_date_from: bool = False,
    limit: int = QUERY_DEFAULT_LIMIT,
    offset: int = 0,
) -> List:
    # Note: This code is inefficient and problematic, see https://github.com/PostHog/posthog/issues/13485 for details.
    # To isolate its impact from rest of the queries its queries are run on different nodes as part of "offline" workloads.
    hogql_context = HogQLContext(within_non_hogql_query=True)

    limit += 1
    limit_sql = "LIMIT %(limit)s"

    if offset > 0:
        limit_sql += " OFFSET %(offset)s"

    conditions, condition_params = determine_event_conditions(
        {
            "after": None if unbounded_date_from else (now() - timedelta(days=1)).isoformat(),
            "before": (now() + timedelta(seconds=5)).isoformat(),
            **request_get_query_dict,
        }
    )
    prop_filters, prop_filter_params = parse_prop_grouped_clauses(
        team_id=team.pk, property_group=filter.property_groups, has_person_id_joined=False, hogql_context=hogql_context
    )

    if action_id:
        try:
            action = Action.objects.get(pk=action_id, team_id=team.pk)
        except Action.DoesNotExist:
            return []
        if action.steps.count() == 0:
            return []

        action_query, params = format_action_filter(team_id=team.pk, action=action, hogql_context=hogql_context)
        prop_filters += " AND {}".format(action_query)
        prop_filter_params = {**prop_filter_params, **params}

    order = "DESC" if len(order_by) == 1 and order_by[0] == "-timestamp" else "ASC"
    if prop_filters != "":
        return insight_query_with_columns(
            SELECT_EVENT_BY_TEAM_AND_CONDITIONS_FILTERS_SQL.format(
                conditions=conditions, limit=limit_sql, filters=prop_filters, order=order
            ),
            {
                "team_id": team.pk,
                "limit": limit,
                "offset": offset,
                **condition_params,
                **prop_filter_params,
                **hogql_context.values,
            },
            query_type="events_list",
            workload=Workload.OFFLINE,
        )
    else:
        return insight_query_with_columns(
            SELECT_EVENT_BY_TEAM_AND_CONDITIONS_SQL.format(conditions=conditions, limit=limit_sql, order=order),
            {
                "team_id": team.pk,
                "limit": limit,
                "offset": offset,
                **condition_params,
                **hogql_context.values,
            },
            query_type="events_list",
            workload=Workload.OFFLINE,
        )
