from typing import List

from posthog.clickhouse.client.connection import Workload
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.utils import action_to_expr, has_aggregation, property_to_expr
from posthog.models import Action, Team
from posthog.models.event.query_event_list import QUERY_DEFAULT_LIMIT, QUERY_MAXIMUM_LIMIT, EventsQueryResponse
from posthog.schema import EventsQuery


def run_events_query_v2(
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
    select_input: List[str] = ["1"] if len(query.select) == 0 else query.select
    select: List[ast.Expr] = [parse_expr(column) for column in select_input]
    group_by: List[ast.Expr] = [column for column in select if not has_aggregation(column)]
    has_any_aggregation = any(has_aggregation(column) for column in select)

    # TODO: support determine_event_conditions

    # where & having
    where_input = query.where or []
    where_exprs = [parse_expr(expr) for expr in where_input]
    if query.actionId:
        try:
            action = Action.objects.get(pk=query.actionId, team_id=team.pk)
        except Action.DoesNotExist:
            raise Exception("Action does not exist")
        if action.steps.count() == 0:
            raise Exception("Action does not have any match groups")
        where_exprs.append(action_to_expr(action))
    if query.properties:
        where_exprs.extend(property_to_expr(property) for property in query.properties)
    if query.fixedProperties:
        where_exprs.extend(property_to_expr(property) for property in query.fixedProperties)

    where_list = [expr for expr in where_exprs if not has_aggregation(expr)]
    where = ast.And(values=where_list) if len(where_list) > 0 else None
    having_list = [expr for expr in where_exprs if has_aggregation(expr)]
    having = ast.And(values=having_list) if len(having_list) > 0 else None

    stmt = ast.SelectQuery(
        select=select,
        where=where,
        having=having,
        group_by=group_by if has_any_aggregation else None,
        limit=limit,
        offset=offset,
    )

    query_result = execute_hogql_query(query=stmt, team=team, workload=Workload.OFFLINE, query_type="EventsQuery")
    received_extra_row = len(query_result.results) == limit  # limit was +=1'd above

    return EventsQueryResponse(
        results=query_result.results[: limit - 1] if received_extra_row else query_result.results,
        columns=select_input,
        types=[type for _, type in query_result.types],
        hasMore=received_extra_row,
    )
