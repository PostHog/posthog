import json
from datetime import timedelta
from typing import List, Optional, Tuple

from dateutil.parser import isoparse
from django.utils.timezone import now

from posthog.api.element import ElementSerializer
from posthog.api.utils import get_pk_or_uuid
from posthog.clickhouse.client.connection import Workload
from posthog.hogql import ast
from posthog.hogql.constants import SELECT_STAR_FROM_EVENTS_FIELDS
from posthog.hogql.parser import parse_expr, parse_order_expr
from posthog.hogql.property import action_to_expr, has_aggregation, property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.models import Action, Person, Team
from posthog.models.element import chain_to_elements
from posthog.schema import EventsQuery, EventsQueryResponse
from posthog.utils import relative_date_parse

QUERY_DEFAULT_LIMIT = 100
QUERY_DEFAULT_EXPORT_LIMIT = 3_500
QUERY_MAXIMUM_LIMIT = 100_000


def run_events_query(
    team: Team,
    query: EventsQuery,
) -> EventsQueryResponse:
    # Note: This code is inefficient and problematic, see https://github.com/PostHog/posthog/issues/13485 for details.
    # To isolate its impact from rest of the queries its queries are run on different nodes as part of "offline" workloads.

    # limit & offset
    # adding +1 to the limit to check if there's a "next page" after the requested results
    limit = min(QUERY_MAXIMUM_LIMIT, QUERY_DEFAULT_LIMIT if query.limit is None else query.limit) + 1
    offset = 0 if query.offset is None else query.offset

    # columns & group_by
    select_input_raw = ["*"] if len(query.select) == 0 else query.select
    select_input: List[str] = []
    for col in select_input_raw:
        # Selecting a "*" expands the list of columns, resulting in a table that's not what we asked for.
        # Instead, ask for a tuple with all the columns we want. Later transform this back into a dict.
        if col == "*":
            select_input.append(f"tuple({', '.join(SELECT_STAR_FROM_EVENTS_FIELDS)})")
        elif col == "person":
            # Select just enough person fields to show the name/email in the UI. Put it back into a dict later.
            select_input.append(
                "tuple(distinct_id, person_id, person.created_at, person.properties.name, person.properties.email)"
            )
        else:
            select_input.append(col)

    select: List[ast.Expr] = [parse_expr(column) for column in select_input]
    group_by: List[ast.Expr] = [column for column in select if not has_aggregation(column)]
    aggregations: List[ast.Expr] = [column for column in select if has_aggregation(column)]
    has_any_aggregation = len(aggregations) > 0

    # filters
    where_input = query.where or []
    where_exprs = [parse_expr(expr) for expr in where_input]
    if query.properties:
        where_exprs.extend(property_to_expr(property) for property in query.properties)
    if query.fixedProperties:
        where_exprs.extend(property_to_expr(property) for property in query.fixedProperties)
    if query.event:
        where_exprs.append(parse_expr("event = {event}", {"event": ast.Constant(value=query.event)}))
    if query.actionId:
        try:
            action = Action.objects.get(pk=query.actionId, team_id=team.pk)
        except Action.DoesNotExist:
            raise Exception("Action does not exist")
        if action.steps.count() == 0:
            raise Exception("Action does not have any match groups")
        where_exprs.append(action_to_expr(action))
    if query.personId:
        person: Optional[Person] = get_pk_or_uuid(Person.objects.all(), query.personId).first()
        distinct_ids = person.distinct_ids if person is not None else []
        ids_list = list(map(str, distinct_ids))
        where_exprs.append(parse_expr("distinct_id in {list}", {"list": ast.Constant(value=ids_list)}))

    # prevent accidentally future events from being visible by default
    before = query.before or (now() + timedelta(seconds=5)).isoformat()
    try:
        timestamp = isoparse(before).strftime("%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        timestamp = relative_date_parse(before).strftime("%Y-%m-%d %H:%M:%S.%f")
    where_exprs.append(parse_expr("timestamp < {timestamp}", {"timestamp": ast.Constant(value=timestamp)}))

    # limit to the last 24h by default
    after = query.after or "-24h"
    try:
        timestamp = isoparse(after).strftime("%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        timestamp = relative_date_parse(after).strftime("%Y-%m-%d %H:%M:%S.%f")
    where_exprs.append(parse_expr("timestamp > {timestamp}", {"timestamp": ast.Constant(value=timestamp)}))

    # where & having
    where_list = [expr for expr in where_exprs if not has_aggregation(expr)]
    where = ast.And(exprs=where_list) if len(where_list) > 0 else None
    having_list = [expr for expr in where_exprs if has_aggregation(expr)]
    having = ast.And(exprs=having_list) if len(having_list) > 0 else None

    # order by
    if query.orderBy is not None:
        order_by = [parse_order_expr(column) for column in query.orderBy]
    elif "count()" in select_input:
        order_by = [ast.OrderExpr(expr=parse_expr("count()"), order="DESC")]
    elif len(aggregations) > 0:
        order_by = [ast.OrderExpr(expr=aggregations[0], order="DESC")]
    elif "timestamp" in select_input:
        order_by = [ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")]
    elif len(select) > 0:
        order_by = [ast.OrderExpr(expr=select[0], order="ASC")]
    else:
        order_by = []

    stmt = ast.SelectQuery(
        select=select,
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=where,
        having=having,
        group_by=group_by if has_any_aggregation else None,
        order_by=order_by,
        limit=ast.Constant(value=limit),
        offset=ast.Constant(value=offset),
    )

    query_result = execute_hogql_query(query=stmt, team=team, workload=Workload.OFFLINE, query_type="EventsQuery")

    # Convert star field from tuple to dict in each result
    if "*" in select_input_raw:
        star_idx = select_input_raw.index("*")
        for index, result in enumerate(query_result.results):
            query_result.results[index] = list(result)
            select = result[star_idx]
            new_result = dict(zip(SELECT_STAR_FROM_EVENTS_FIELDS, select))
            new_result["properties"] = json.loads(new_result["properties"])
            if new_result["elements_chain"]:
                new_result["elements"] = ElementSerializer(
                    chain_to_elements(new_result["elements_chain"]), many=True
                ).data
            new_result["person"] = {
                "id": new_result["person_id"],
                "created_at": new_result["person.created_at"],
                "properties": json.loads(new_result["person.properties"]),
                "distinct_ids": [new_result["distinct_id"]],
            }
            del new_result["person_id"]
            del new_result["person.created_at"]
            del new_result["person.properties"]
            query_result.results[index][star_idx] = new_result

    # Convert person field from tuple to dict in each result
    if "person" in select_input_raw:
        person_idx = select_input_raw.index("person")
        for index, result in enumerate(query_result.results):
            person_tuple: Tuple = result[person_idx]
            query_result.results[index] = list(result)
            query_result.results[index][person_idx] = {
                "id": person_tuple[1],
                "created_at": person_tuple[2],
                "properties": {"name": person_tuple[3], "email": person_tuple[4]},
                "distinct_ids": [person_tuple[0]],
            }

    received_extra_row = len(query_result.results) == limit  # limit was +=1'd above
    return EventsQueryResponse(
        results=query_result.results[: limit - 1] if received_extra_row else query_result.results,
        columns=select_input_raw,
        types=[type for _, type in query_result.types],
        hasMore=received_extra_row,
    )
