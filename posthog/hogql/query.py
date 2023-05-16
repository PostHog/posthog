from typing import Dict, List, Optional, Union, cast

from pydantic import BaseModel, Extra

from posthog.clickhouse.client.connection import Workload
from posthog.hogql import ast
from posthog.hogql.constants import DEFAULT_RETURNED_ROWS, HogQLSettings
from posthog.hogql.hogql import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import assert_no_placeholders, replace_placeholders
from posthog.hogql.printer import prepare_ast_for_printing, print_ast, print_prepared_ast
from posthog.hogql.visitor import clone_expr
from posthog.models.team import Team
from posthog.queries.insight import insight_sync_execute


class HogQLQueryResponse(BaseModel):
    class Config:
        extra = Extra.forbid

    clickhouse: Optional[str] = None
    columns: Optional[List] = None
    hogql: Optional[str] = None
    query: Optional[str] = None
    results: Optional[List] = None
    types: Optional[List] = None


def execute_hogql_query(
    query: Union[str, ast.SelectQuery],
    team: Team,
    query_type: str = "hogql_query",
    placeholders: Optional[Dict[str, ast.Expr]] = None,
    workload: Workload = Workload.ONLINE,
    settings: Optional[HogQLSettings] = None,
) -> HogQLQueryResponse:
    if isinstance(query, ast.SelectQuery):
        select_query = query
        query = None
    else:
        select_query = parse_select(str(query))

    if placeholders:
        select_query = replace_placeholders(select_query, placeholders)
    else:
        assert_no_placeholders(select_query)

    if select_query.limit is None:
        select_query.limit = ast.Constant(value=DEFAULT_RETURNED_ROWS)

    # Get printed HogQL query, and returned columns. Using a cloned query.
    hogql_query_context = HogQLContext(
        team_id=team.pk, enable_select_queries=True, person_on_events_mode=team.person_on_events_mode
    )
    select_query_hogql = cast(
        ast.SelectQuery,
        prepare_ast_for_printing(node=clone_expr(select_query, True), context=hogql_query_context, dialect="hogql"),
    )
    hogql = print_prepared_ast(select_query_hogql, hogql_query_context, "hogql")
    print_columns = []
    for node in select_query_hogql.select:
        if isinstance(node, ast.Alias):
            print_columns.append(node.alias)
        else:
            print_columns.append(
                print_prepared_ast(node=node, context=hogql_query_context, dialect="hogql", stack=[select_query_hogql])
            )

    # Print the ClickHouse SQL query
    clickhouse_context = HogQLContext(
        team_id=team.pk, enable_select_queries=True, person_on_events_mode=team.person_on_events_mode
    )
    clickhouse = print_ast(
        select_query, context=clickhouse_context, dialect="clickhouse", settings=settings or HogQLSettings()
    )

    results, types = insight_sync_execute(
        clickhouse,
        clickhouse_context.values,
        with_column_types=True,
        query_type=query_type,
        workload=workload,
    )

    return HogQLQueryResponse(
        query=query,
        hogql=hogql,
        clickhouse=clickhouse,
        results=results,
        columns=print_columns,
        types=types,
    )
