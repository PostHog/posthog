import random
from datetime import datetime, timedelta
from typing import Optional, Union
from zoneinfo import ZoneInfo

from django.conf import settings

from dateutil.parser import isoparse

from posthog.hogql.constants import DEFAULT_RETURNED_ROWS
from posthog.hogql.context import HogQLContext

from posthog.api.utils import get_pk_or_uuid
from posthog.clickhouse.client.connection import Workload
from posthog.models import Action, Filter, Person, Team
from posthog.models.action.util import format_action_filter
from posthog.models.event.sql import (
    SELECT_EVENT_BY_TEAM_AND_CONDITIONS_FILTERS_SQL,
    SELECT_EVENT_BY_TEAM_AND_CONDITIONS_SQL,
)
from posthog.models.person.person import READ_DB_FOR_PERSONS, get_distinct_ids_for_subquery
from posthog.models.property.util import parse_prop_grouped_clauses
from posthog.queries.insight import insight_query_with_columns
from posthog.utils import relative_date_parse


def parse_timestamp(timestamp: str, tzinfo: ZoneInfo) -> datetime:
    try:
        parsed = isoparse(timestamp)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=tzinfo)
        return parsed
    except ValueError:
        return relative_date_parse(timestamp, tzinfo)


def parse_request_params(
    conditions: dict[str, Union[None, str, list[str]]], team: Team, tzinfo: ZoneInfo
) -> tuple[str, dict]:
    result = ""
    params: dict[str, Union[str, list[str]]] = {}
    for k, v in conditions.items():
        if not isinstance(v, str):
            continue
        if k == "after":
            result += "AND timestamp > %(after)s "
            params.update({"after": v})
        elif k == "before":
            result += "AND timestamp < %(before)s "
            params.update({"before": v})
        elif k == "person_id":
            result += """AND distinct_id IN (%(distinct_ids)s) """
            person = get_pk_or_uuid(Person.objects.db_manager(READ_DB_FOR_PERSONS).filter(team=team), v).first()
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
    request_get_query_dict: dict,
    order_by: list[str],
    action_id: Optional[str],
    unbounded_date_from: bool = False,
    limit: int = DEFAULT_RETURNED_ROWS,
    offset: int = 0,
    time_window_seconds: Optional[int] = None,
) -> tuple[list, Optional[int]]:
    # Note: This code is inefficient and problematic, see https://github.com/PostHog/posthog/issues/13485 for details.
    # To isolate its impact from rest of the queries its queries are run on different nodes as part of "offline" workloads.
    hogql_context = HogQLContext(within_non_hogql_query=True, team_id=team.pk, enable_select_queries=True)

    limit += 1
    limit_sql = "LIMIT %(limit)s"

    if offset > 0:
        limit_sql += " OFFSET %(offset)s"

    order = "DESC" if len(order_by) == 1 and order_by[0] == "-timestamp" else "ASC"

    if request_get_query_dict.get("before"):
        request_get_query_dict["before"] = parse_timestamp(request_get_query_dict["before"], team.timezone_info)
    else:
        request_get_query_dict["before"] = datetime.now(team.timezone_info) + timedelta(seconds=5)

    if request_get_query_dict.get("after"):
        request_get_query_dict["after"] = parse_timestamp(request_get_query_dict["after"], team.timezone_info)
    elif settings.PATCH_EVENT_LIST_MAX_OFFSET > 1:
        request_get_query_dict["after"] = request_get_query_dict["before"] - timedelta(hours=24)

    if settings.PATCH_EVENT_LIST_MAX_OFFSET > 0 and request_get_query_dict.get("after"):
        date_range = request_get_query_dict["before"] - request_get_query_dict["after"]
        if date_range > timedelta(days=366) and (settings.PATCH_EVENT_LIST_MAX_OFFSET > 1 or random.random() < 0.01):
            raise ValueError("Date range cannot exceed 1 year")

    applied_window_seconds: Optional[int] = None
    if (
        not unbounded_date_from
        and order == "DESC"
        and time_window_seconds is not None
        and (
            not request_get_query_dict.get("after")
            or (request_get_query_dict["before"] - request_get_query_dict["after"]).total_seconds()
            > time_window_seconds
        )
    ):
        # Apply the specified time window to limit the query range
        request_get_query_dict["after"] = request_get_query_dict["before"] - timedelta(seconds=time_window_seconds)
        applied_window_seconds = time_window_seconds

    request_get_query_dict["before"] = request_get_query_dict["before"].strftime("%Y-%m-%d %H:%M:%S.%f")
    if request_get_query_dict.get("after"):
        request_get_query_dict["after"] = request_get_query_dict["after"].strftime("%Y-%m-%d %H:%M:%S.%f")

    conditions, condition_params = parse_request_params(
        request_get_query_dict,
        team,
        tzinfo=team.timezone_info,
    )

    prop_filters, prop_filter_params = parse_prop_grouped_clauses(
        team_id=team.pk,
        property_group=filter.property_groups,
        has_person_id_joined=False,
        hogql_context=hogql_context,
    )

    if action_id:
        try:
            action = Action.objects.get(pk=action_id, team__project_id=team.project_id)
            if not action.steps:
                return [], applied_window_seconds
        except Action.DoesNotExist:
            return [], applied_window_seconds

        action_query, params = format_action_filter(team_id=team.pk, action=action, hogql_context=hogql_context)
        prop_filters += " AND {}".format(action_query)
        prop_filter_params = {**prop_filter_params, **params}

    if prop_filters != "":
        return (
            insight_query_with_columns(
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
                settings={"max_threads": settings.CLICKHOUSE_EVENT_LIST_MAX_THREADS},
            ),
            applied_window_seconds,
        )
    else:
        return (
            insight_query_with_columns(
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
                settings={"max_threads": settings.CLICKHOUSE_EVENT_LIST_MAX_THREADS},
            ),
            applied_window_seconds,
        )
