import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

from dateutil.parser import isoparse
from django.utils.timezone import now

from posthog.api.utils import get_pk_or_uuid
from posthog.client import query_with_columns, sync_execute
from posthog.hogql.expr_parser import ExprParserContext, translate_hql
from posthog.models import Action, Filter, Person, Team
from posthog.models.action.util import format_action_filter
from posthog.models.element import chain_to_elements
from posthog.models.event.sql import (
    SELECT_EVENT_BY_TEAM_AND_CONDITIONS_FILTERS_SQL,
    SELECT_EVENT_BY_TEAM_AND_CONDITIONS_SQL,
    SELECT_EVENT_FIELDS_BY_TEAM_AND_CONDITIONS_FILTERS,
)
from posthog.models.event.util import ElementSerializer
from posthog.models.property.util import parse_prop_grouped_clauses

SELECT_STAR_FROM_EVENTS_FIELDS = [
    "uuid",
    "event",
    "properties",
    "timestamp",
    "team_id",
    "distinct_id",
    "elements_chain",
    "created_at",
    "person_id",
    "person_created_at",
    "person_properties",
    "group0_properties",
    "group1_properties",
    "group2_properties",
    "group3_properties",
    "group4_properties",
    "group0_created_at",
    "group1_created_at",
    "group2_created_at",
    "group3_created_at",
    "group4_created_at",
]


def determine_event_conditions(
    team: Team, conditions: Dict[str, Union[str, List[str]]], long_date_from: bool
) -> Tuple[str, Dict]:
    result = ""
    params: Dict[str, Union[str, List[str]]] = {}
    for (k, v) in conditions.items():
        if not isinstance(v, str):
            continue
        if k == "after" and not long_date_from:
            timestamp = isoparse(v).strftime("%Y-%m-%d %H:%M:%S.%f")
            result += "AND timestamp > %(after)s"
            params.update({"after": timestamp})
        elif k == "before":
            timestamp = isoparse(v).strftime("%Y-%m-%d %H:%M:%S.%f")
            result += "AND timestamp < %(before)s"
            params.update({"before": timestamp})
        elif k == "person_id":
            result += """AND distinct_id IN (%(distinct_ids)s)"""
            person = get_pk_or_uuid(Person.objects.all(), v).first()
            distinct_ids = person.distinct_ids if person is not None else []
            params.update({"distinct_ids": list(map(str, distinct_ids))})
        elif k == "distinct_id":
            result += "AND distinct_id = %(distinct_id)s"
            params.update({"distinct_id": v})
        elif k == "event":
            result += "AND event = %(event)s"
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
    long_date_from: bool = False,
    limit: int = 100,
) -> Union[List, dict]:
    limit += 1
    limit_sql = "LIMIT %(limit)s"
    order = "DESC" if order_by[0] == "-timestamp" else "ASC"

    selected_columns: List[str] = []
    group_by_columns: List[str] = []

    if isinstance(select, list):
        if len(select) == 0:
            select = ["*"]
        for column in select:
            if column == "*":
                clickhouse_sql = f"tuple({','.join(SELECT_STAR_FROM_EVENTS_FIELDS)})"
                selected_columns.append(clickhouse_sql)
                group_by_columns.append(clickhouse_sql)
            else:
                context = ExprParserContext()
                clickhouse_sql = translate_hql(column, context)
                selected_columns.append(clickhouse_sql)
                if not context.is_aggregation:
                    group_by_columns.append(clickhouse_sql)

    conditions, condition_params = determine_event_conditions(
        team,
        {
            "after": (now() - timedelta(days=1)).isoformat(),
            "before": (now() + timedelta(seconds=5)).isoformat(),
            **request_get_query_dict,
        },
        long_date_from,
    )
    prop_filters, prop_filter_params = parse_prop_grouped_clauses(
        team_id=team.pk, property_group=filter.property_groups, has_person_id_joined=False
    )

    having_filters: List[str] = []
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

    if where:
        for experssion in where:
            context = ExprParserContext()
            clickhouse_sql = translate_hql(experssion, context)
            if context.is_aggregation:
                having_filters.append(clickhouse_sql)
            else:
                prop_filters += " AND {}".format(clickhouse_sql)

    if selected_columns:
        order_by_list = []
        if order_by:
            for fragment in order_by:
                order_direction = "ASC"
                if fragment.startswith("-"):
                    order_direction = "DESC"
                    fragment = fragment[1:]
                order_by_list.append(translate_hql(fragment) + " " + order_direction)
        else:
            order_by_list.append(selected_columns[0])

        results, types = sync_execute(
            SELECT_EVENT_FIELDS_BY_TEAM_AND_CONDITIONS_FILTERS.format(
                columns=", ".join(selected_columns),
                conditions=conditions,
                filters=prop_filters,
                group="GROUP BY {}".format(", ".join(group_by_columns)) if group_by_columns else "",
                having="HAVING {}".format(" AND ".join(having_filters)) if having_filters else "",
                order="ORDER BY {}".format(", ".join(order_by_list)),
                limit=limit_sql,
            ),
            {"team_id": team.pk, "limit": limit, **condition_params, **prop_filter_params},
            with_column_types=True,
        )

        # Convert star result from tuple to dict
        if "*" in select:
            star = select.index("*")
            for index, result in enumerate(results):
                results[index] = list(result)
                results[index][star] = convert_star_select_to_dict(result[star])

        return {
            "results": results,
            "columns": select,
            "types": [type for _, type in types],
        }

    if prop_filters != "":
        return query_with_columns(
            SELECT_EVENT_BY_TEAM_AND_CONDITIONS_FILTERS_SQL.format(
                conditions=conditions, limit=limit_sql, filters=prop_filters, order=order
            ),
            {"team_id": team.pk, "limit": limit, **condition_params, **prop_filter_params},
        )
    else:
        return query_with_columns(
            SELECT_EVENT_BY_TEAM_AND_CONDITIONS_SQL.format(conditions=conditions, limit=limit_sql, order=order),
            {"team_id": team.pk, "limit": limit, **condition_params},
        )


def parse_order_by(order_by_param: Optional[str], select: Optional[List[str]]) -> List[str]:
    if order_by_param:
        return list(json.loads(order_by_param))
    if not select:
        return ["-timestamp"]
    if "total()" in select:
        return ["-total()"]
    if "*" in select:
        return ["-timestamp"]

    return [select[0]]


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
    for i in range(5):
        if (
            isinstance(new_result[f"group{i}_created_at"], datetime)
            and new_result[f"group{i}_created_at"].timestamp() != 0
        ):
            new_result[f"group{i}"] = {
                "created_at": new_result[f"group{i}_created_at"],
                "properties": json.loads(new_result[f"group{i}_properties"])
                if new_result[f"group{i}_properties"]
                else {},
            }
        new_result.pop(f"group{i}_properties")
        new_result.pop(f"group{i}_created_at")
    if new_result["elements_chain"]:
        new_result["elements"] = ElementSerializer(chain_to_elements(new_result["elements_chain"]), many=True).data
    return new_result
