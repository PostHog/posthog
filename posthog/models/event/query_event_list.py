import dataclasses
import json
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

from dateutil.parser import isoparse
from django.utils.timezone import now

from posthog.api.utils import get_pk_or_uuid
from posthog.hogql.expr_parser import SELECT_STAR_FROM_EVENTS_FIELDS, ExprParserContext, translate_hql
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


# sync with "schema.ts"
@dataclasses.dataclass
class EventsQueryResponse:
    columns: List[str] = dataclasses.field(default_factory=list)
    types: List[str] = dataclasses.field(default_factory=list)
    results: List[List[Any]] = dataclasses.field(default_factory=list)


def determine_event_conditions(conditions: Dict[str, Union[None, str, List[str]]]) -> Tuple[str, Dict]:
    result = ""
    params: Dict[str, Union[str, List[str]]] = {}
    for (k, v) in conditions.items():
        if not isinstance(v, str):
            continue
        if k == "after":
            timestamp = isoparse(v).strftime("%Y-%m-%d %H:%M:%S.%f")
            result += "AND timestamp > %(after)s "
            params.update({"after": timestamp})
        elif k == "before":
            timestamp = isoparse(v).strftime("%Y-%m-%d %H:%M:%S.%f")
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
    select: Optional[List[str]],
    where: Optional[List[str]],
    unbounded_date_from: bool = False,
    limit: int = 100,
) -> Union[List, EventsQueryResponse]:
    limit += 1
    limit_sql = "LIMIT %(limit)s"

    conditions, condition_params = determine_event_conditions(
        {
            "after": None if unbounded_date_from else (now() - timedelta(days=1)).isoformat(),
            "before": (now() + timedelta(seconds=5)).isoformat(),
            **request_get_query_dict,
        }
    )
    prop_filters, prop_filter_params = parse_prop_grouped_clauses(
        team_id=team.pk, property_group=filter.property_groups, has_person_id_joined=False
    )

    if action_id:
        try:
            action = Action.objects.get(pk=action_id, team_id=team.pk)
        except Action.DoesNotExist:
            return []
        if action.steps.count() == 0:
            return []

        # NOTE: never accepts cohort parameters so no need for explicit person_id_joined_alias
        action_query, params = format_action_filter(team_id=team.pk, action=action)
        prop_filters += " AND {}".format(action_query)
        prop_filter_params = {**prop_filter_params, **params}

    # if not using hogql-powered "select" to fetch certain columns, return an array of objects
    if not isinstance(select, list):
        order = "DESC" if len(order_by) == 1 and order_by[0] == "-timestamp" else "ASC"
        if where:
            raise ValueError("Cannot use 'where' without 'select'")
        if prop_filters != "":
            return insight_query_with_columns(
                SELECT_EVENT_BY_TEAM_AND_CONDITIONS_FILTERS_SQL.format(
                    conditions=conditions, limit=limit_sql, filters=prop_filters, order=order
                ),
                {"team_id": team.pk, "limit": limit, **condition_params, **prop_filter_params},
                query_type="events_list",
            )
        else:
            return insight_query_with_columns(
                SELECT_EVENT_BY_TEAM_AND_CONDITIONS_SQL.format(conditions=conditions, limit=limit_sql, order=order),
                {"team_id": team.pk, "limit": limit, **condition_params},
                query_type="events_list",
            )

    # events list v2 - hogql

    collected_hogql_values: Dict[str, Any] = {}
    select_columns: List[str] = []
    group_by_columns: List[str] = []
    where_filters: List[str] = []
    having_filters: List[str] = []
    order_by_list: List[str] = []

    if len(select) == 0:
        select = ["*"]

    for expr in select:
        context = ExprParserContext()
        context.collect_values = collected_hogql_values
        clickhouse_sql = translate_hql(expr, context)
        select_columns.append(clickhouse_sql)
        if not context.is_aggregation:
            group_by_columns.append(clickhouse_sql)

    for expr in where or []:
        context = ExprParserContext()
        context.collect_values = collected_hogql_values
        clickhouse_sql = translate_hql(expr, context)
        if context.is_aggregation:
            having_filters.append(clickhouse_sql)
        else:
            where_filters.append(clickhouse_sql)

    if order_by:
        for fragment in order_by:
            order_direction = "ASC"
            if fragment.startswith("-"):
                order_direction = "DESC"
                fragment = fragment[1:]
            context = ExprParserContext()
            context.collect_values = collected_hogql_values
            order_by_list.append(translate_hql(fragment, context) + " " + order_direction)
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
            limit=f"LIMIT {int(limit)}",
        ),
        {"team_id": team.pk, **condition_params, **prop_filter_params, **collected_hogql_values},
        with_column_types=True,
        query_type="events_list",
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

    return EventsQueryResponse(
        results=results,
        columns=select,
        types=[type for _, type in types],
    )


def convert_star_select_to_dict(select: Tuple[Any]) -> Dict[str, Any]:
    new_result = dict(zip(SELECT_STAR_FROM_EVENTS_FIELDS, select))
    new_result["properties"] = json.loads(new_result["properties"])
    new_result["person"] = {
        "id": new_result["person_id"],
        "created_at": new_result["person_created_at"],
        "properties": json.loads(new_result["person_properties"]),
    }
    new_result.pop("person_id")
    new_result.pop("person_created_at")
    new_result.pop("person_properties")
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
