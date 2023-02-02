import json
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

from dateutil.parser import isoparse
from django.utils.timezone import now
from pydantic import BaseModel

from posthog.api.utils import get_pk_or_uuid
from posthog.clickhouse.client.connection import Workload
from posthog.hogql.constants import SELECT_STAR_FROM_EVENTS_FIELDS
from posthog.hogql.hogql import HogQLContext, translate_hogql
from posthog.models import Action, Filter, Person, Team
from posthog.models.action.util import format_action_filter
from posthog.models.element import chain_to_elements
from posthog.models.event.sql import (
    SELECT_EVENT_BY_TEAM_AND_CONDITIONS_FILTERS_SQL,
    SELECT_EVENT_BY_TEAM_AND_CONDITIONS_SQL,
    SELECT_EVENT_FIELDS_BY_TEAM_AND_CONDITIONS_FILTERS_PART,
)
from posthog.models.event.util import ElementSerializer
from posthog.models.property.util import parse_prop_grouped_clauses
from posthog.queries.insight import insight_query_with_columns, insight_sync_execute
from posthog.schema import EventsQuery
from posthog.utils import relative_date_parse

# Return at most this number of events in CSV export
QUERY_DEFAULT_LIMIT = 100
QUERY_DEFAULT_EXPORT_LIMIT = 3_500
QUERY_MAXIMUM_LIMIT = 100_000


class EventsQueryResponse(BaseModel):
    columns: List[str]
    types: List[str]
    results: List[List]
    hasMore: bool


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
    hogql_context = HogQLContext()

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


def run_events_query(
    team: Team,
    query: EventsQuery,
) -> EventsQueryResponse:
    # Note: This code is inefficient and problematic, see https://github.com/PostHog/posthog/issues/13485 for details.
    # To isolate its impact from rest of the queries its queries are run on different nodes as part of "offline" workloads.
    hogql_context = HogQLContext()

    # adding +1 to the limit to check if there's a "next page" after the requested results
    limit = min(QUERY_MAXIMUM_LIMIT, QUERY_DEFAULT_LIMIT if query.limit is None else query.limit) + 1
    offset = 0 if query.offset is None else query.offset
    action_id = query.actionId
    person_id = query.personId
    order_by = query.orderBy
    select = query.select
    where = query.where
    event = query.event

    properties = []
    properties.extend(query.fixedProperties or [])
    properties.extend(query.properties or [])

    limit_sql = "LIMIT %(limit)s"
    if offset > 0:
        limit_sql += " OFFSET %(offset)s"

    conditions, condition_params = determine_event_conditions(
        {
            # Don't show events that have been ingested with timestamps in the future. Would break new event polling.
            "after": query.after,
            "before": query.before or (now() + timedelta(seconds=5)).isoformat(),
            "person_id": person_id,
            "event": event,
        }
    )
    filter = Filter(team=team, data={"properties": [p.dict() for p in properties]}, hogql_context=hogql_context)
    prop_filters, prop_filter_params = parse_prop_grouped_clauses(
        team_id=team.pk, property_group=filter.property_groups, has_person_id_joined=False, hogql_context=hogql_context
    )

    if action_id:
        try:
            action = Action.objects.get(pk=action_id, team_id=team.pk)
        except Action.DoesNotExist:
            raise Exception("Action does not exist")
        if action.steps.count() == 0:
            raise Exception("Action does not have any match groups")

        action_query, params = format_action_filter(team_id=team.pk, action=action, hogql_context=hogql_context)
        prop_filters += " AND {}".format(action_query)
        prop_filter_params = {**prop_filter_params, **params}

    select_columns: List[str] = []
    group_by_columns: List[str] = []
    where_filters: List[str] = []
    having_filters: List[str] = []
    order_by_list: List[str] = []

    if len(select) == 0:
        select = ["*"]

    for expr in select:
        hogql_context.found_aggregation = False
        clickhouse_sql = translate_hogql(expr, hogql_context)
        select_columns.append(clickhouse_sql)
        if not hogql_context.found_aggregation:
            group_by_columns.append(clickhouse_sql)

    for expr in where or []:
        hogql_context.found_aggregation = False
        clickhouse_sql = translate_hogql(expr, hogql_context)
        if hogql_context.found_aggregation:
            having_filters.append(clickhouse_sql)
        else:
            where_filters.append(clickhouse_sql)

    if order_by:
        for fragment in order_by:
            order_direction = "ASC"
            if fragment.startswith("-"):
                order_direction = "DESC"
                fragment = fragment[1:]
            order_by_list.append(translate_hogql(fragment, hogql_context) + " " + order_direction)
    else:
        if "count(*)" in select_columns or "count()" in select_columns:
            order_by_list.append("count() DESC")
        elif "timestamp" in select_columns:
            order_by_list.append("timestamp DESC")
        else:
            order_by_list.append(select_columns[0] + " ASC")

    if select_columns == group_by_columns:
        group_by_columns = []

    results, types = insight_sync_execute(
        SELECT_EVENT_FIELDS_BY_TEAM_AND_CONDITIONS_FILTERS_PART.format(
            columns=", ".join(select_columns),
            conditions=conditions,
            filters=prop_filters,
            where="AND {}".format(" AND ".join(where_filters)) if where_filters else "",
            group="GROUP BY {}".format(", ".join(group_by_columns)) if group_by_columns else "",
            having="HAVING {}".format(" AND ".join(having_filters)) if having_filters else "",
            order="ORDER BY {}".format(", ".join(order_by_list)) if order_by_list else "",
            limit=limit_sql,
        ),
        {
            "team_id": team.pk,
            "limit": limit,
            "offset": offset,
            **condition_params,
            **prop_filter_params,
            **hogql_context.values,
        },
        with_column_types=True,
        query_type="events_list",
        workload=Workload.OFFLINE,
    )

    # Convert star field from tuple to dict in each result
    if "*" in select:
        star = select.index("*")
        for index, result in enumerate(results):
            results[index] = list(result)
            results[index][star] = convert_star_select_to_dict(result[star])

    # Convert person field from tuple to dict in each result
    if "person" in select:
        person = select.index("person")
        for index, result in enumerate(results):
            results[index] = list(result)
            results[index][person] = convert_person_select_to_dict(result[person])

    received_extra_row = len(results) == limit  # limit was +=1'd above

    return EventsQueryResponse(
        results=results[: limit - 1] if received_extra_row else results,
        columns=select,
        types=[type for _, type in types],
        hasMore=received_extra_row,
    )


def convert_star_select_to_dict(select: Tuple[Any]) -> Dict[str, Any]:
    new_result = dict(zip(SELECT_STAR_FROM_EVENTS_FIELDS, select))
    new_result["properties"] = json.loads(new_result["properties"])
    new_result["person"] = {
        "id": new_result["person.id"],
        "created_at": new_result["person.created_at"],
        "properties": json.loads(new_result["person.properties"]),
    }
    new_result.pop("person.id")
    new_result.pop("person.created_at")
    new_result.pop("person.properties")
    if new_result["elements_chain"]:
        new_result["elements"] = ElementSerializer(chain_to_elements(new_result["elements_chain"]), many=True).data
    return new_result


def convert_person_select_to_dict(select: Tuple[str, str, str, str, str]) -> Dict[str, Any]:
    return {
        "id": select[1],
        "created_at": select[2],
        "properties": {"name": select[3], "email": select[4]},
        "distinct_ids": [select[0]],
    }
