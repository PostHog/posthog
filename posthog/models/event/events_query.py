from datetime import timedelta
from typing import List, Optional

from dateutil.parser import isoparse
from django.utils.timezone import now

from posthog.api.utils import get_pk_or_uuid
from posthog.clickhouse.client.connection import Workload
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.utils import action_to_expr, has_aggregation, property_to_expr
from posthog.models import Action, Person, Team
from posthog.models.event.query_event_list import (
    QUERY_DEFAULT_LIMIT,
    QUERY_MAXIMUM_LIMIT,
    EventsQueryResponse,
    convert_person_select_to_dict,
    convert_star_select_to_dict,
)
from posthog.schema import EventsQuery
from posthog.utils import relative_date_parse


def run_events_query_v3(
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
    select_input: List[str] = ["*"] if len(query.select) == 0 else query.select
    select: List[ast.Expr] = [parse_expr(column) for column in select_input]
    group_by: List[ast.Expr] = [column for column in select if not has_aggregation(column)]
    has_any_aggregation = any(has_aggregation(column) for column in select)

    # filters
    where_input = query.where or []
    where_exprs = [parse_expr(expr) for expr in where_input]
    if query.properties:
        where_exprs.extend(property_to_expr(property) for property in query.properties)
    if query.fixedProperties:
        where_exprs.extend(property_to_expr(property) for property in query.fixedProperties)
    if query.event:
        where_exprs.append(
            ast.CompareOperation(
                left=ast.FieldAccess(field="event"),
                right=ast.Constant(value=query.event),
                op=ast.CompareOperationType.Eq,
            )
        )
    if query.before:
        # prevent accidentally future events from being visible by default
        before = query.before or (now() + timedelta(seconds=5)).isoformat()
        try:
            timestamp = isoparse(before).strftime("%Y-%m-%d %H:%M:%S.%f")
        except ValueError:
            timestamp = relative_date_parse(before).strftime("%Y-%m-%d %H:%M:%S.%f")
        where_exprs.append(
            ast.CompareOperation(
                left=ast.FieldAccess(field="timestamp"),
                right=ast.Constant(value=timestamp),
                op=ast.CompareOperationType.Lt,
            )
        )
    if query.after:
        try:
            timestamp = isoparse(query.after).strftime("%Y-%m-%d %H:%M:%S.%f")
        except ValueError:
            timestamp = relative_date_parse(query.after).strftime("%Y-%m-%d %H:%M:%S.%f")
        where_exprs.append(
            ast.CompareOperation(
                left=ast.FieldAccess(field="timestamp"),
                right=ast.Constant(value=timestamp),
                op=ast.CompareOperationType.Gt,
            )
        )
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
        where_exprs.append(
            ast.CompareOperation(
                left=ast.FieldAccess(field="distinct_id"),
                right=ast.Constant(value=ids_list),
                op=ast.CompareOperationType.In,
            )
        )

    # where & having
    where_list = [expr for expr in where_exprs if not has_aggregation(expr)]
    where = ast.And(exprs=where_list) if len(where_list) > 0 else None
    having_list = [expr for expr in where_exprs if has_aggregation(expr)]
    having = ast.And(exprs=having_list) if len(having_list) > 0 else None

    # order by
    # TODO

    stmt = ast.SelectQuery(
        select=select,
        select_from=ast.JoinExpr(table=ast.FieldAccess(field="events")),
        where=where,
        having=having,
        group_by=group_by if has_any_aggregation else None,
        limit=limit,
        offset=offset,
    )

    query_result = execute_hogql_query(query=stmt, team=team, workload=Workload.OFFLINE, query_type="EventsQuery")

    # Convert star field from tuple to dict in each result
    if "*" in select_input:
        star_idx = select_input.index("*")
        for index, result in enumerate(query_result.results):
            query_result.results[index] = list(result)
            query_result.results[index][star_idx] = convert_star_select_to_dict(result[star_idx])

    # Convert person field from tuple to dict in each result
    if "person" in select_input:
        person_idx = select_input.index("person")
        for index, result in enumerate(query_result.results):
            query_result.results[index] = list(result)
            query_result.results[index][person_idx] = convert_person_select_to_dict(result[person_idx])

    received_extra_row = len(query_result.results) == limit  # limit was +=1'd above
    return EventsQueryResponse(
        results=query_result.results[: limit - 1] if received_extra_row else query_result.results,
        columns=select_input,
        types=[type for _, type in query_result.types],
        hasMore=received_extra_row,
    )
