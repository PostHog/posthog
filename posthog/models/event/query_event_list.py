from datetime import timedelta, datetime, time
from typing import Dict, List, Optional, Tuple, Union
from zoneinfo import ZoneInfo

from dateutil.parser import isoparse
from django.utils.timezone import now

from posthog.api.utils import get_pk_or_uuid
from posthog.clickhouse.client.connection import Workload
from posthog.hogql.constants import DEFAULT_RETURNED_ROWS
from posthog.hogql.context import HogQLContext
from posthog.models import Action, Filter, Person, Team
from posthog.models.action.util import format_action_filter
from posthog.models.event.sql import (
    SELECT_EVENT_BY_TEAM_AND_CONDITIONS_FILTERS_SQL,
    SELECT_EVENT_BY_TEAM_AND_CONDITIONS_SQL,
)
from posthog.models.person.person import get_distinct_ids_for_subquery
from posthog.models.property.util import parse_prop_grouped_clauses
from posthog.queries.insight import insight_query_with_columns
from posthog.utils import relative_date_parse


def parse_timestamp(timestamp: str, tzinfo: ZoneInfo) -> datetime:
    try:
        return isoparse(timestamp)
    except ValueError:
        return relative_date_parse(timestamp, tzinfo)


def parse_request_params(
    conditions: Dict[str, Union[None, str, List[str]]], team: Team, tzinfo: ZoneInfo
) -> Tuple[str, Dict]:
    result = ""
    params: Dict[str, Union[str, List[str]]] = {}
    for k, v in conditions.items():
        if not isinstance(v, str):
            continue
        if k == "after":
            timestamp = parse_timestamp(v, tzinfo)
            result += "AND timestamp > %(after)s "
            params.update({"after": timestamp})
        elif k == "before":
            timestamp = parse_timestamp(v, tzinfo)
            result += "AND timestamp < %(before)s "
            params.update({"before": timestamp})
        elif k == "person_id":
            result += """AND distinct_id IN (%(distinct_ids)s) """
            person = get_pk_or_uuid(Person.objects.filter(team=team), v).first()
            params.update({"distinct_ids": get_distinct_ids_for_subquery(person, team)})
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
    limit: int = DEFAULT_RETURNED_ROWS,
    offset: int = 0,
) -> List:
    # Note: This code is inefficient and problematic, see https://github.com/PostHog/posthog/issues/13485 for details.
    # To isolate its impact from rest of the queries its queries are run on different nodes as part of "offline" workloads.
    hogql_context = HogQLContext(within_non_hogql_query=True, team_id=team.pk, enable_select_queries=True)

    limit += 1
    limit_sql = "LIMIT %(limit)s"

    if offset > 0:
        limit_sql += " OFFSET %(offset)s"

    order = "DESC" if len(order_by) == 1 and order_by[0] == "-timestamp" else "ASC"
    conditions, condition_params = parse_request_params(
        request_get_query_dict,
        team,
        tzinfo=team.timezone_info,
    )

    if "before" not in condition_params:
        condition_params["before"] = now() + timedelta(seconds=5)

    if not unbounded_date_from and order == "DESC":
        # If this is the first try, only load the current day
        condition_params["after"] = datetime.combine(condition_params["before"], time.min)

    condition_params["before"] = condition_params["before"].strftime("%Y-%m-%d %H:%M:%S.%f")
    if condition_params["after"]:
        condition_params["after"] = condition_params["after"].strftime("%Y-%m-%d %H:%M:%S.%f")

    prop_filters, prop_filter_params = parse_prop_grouped_clauses(
        team_id=team.pk,
        property_group=filter.property_groups,
        has_person_id_joined=False,
        hogql_context=hogql_context,
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

    if prop_filters != "":
        return insight_query_with_columns(
            SELECT_EVENT_BY_TEAM_AND_CONDITIONS_FILTERS_SQL.format(
                conditions=conditions,
                limit=limit_sql,
                filters=prop_filters,
                order=order,
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
            team_id=team.pk,
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
            team_id=team.pk,
        )
