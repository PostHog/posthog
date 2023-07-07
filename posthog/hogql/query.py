from typing import Dict, Optional, Union, cast

from posthog.clickhouse.client.connection import Workload
from posthog.hogql import ast
from posthog.hogql.constants import HogQLSettings
from posthog.hogql.hogql import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import replace_placeholders
from posthog.hogql.printer import prepare_ast_for_printing, print_ast, print_prepared_ast
from posthog.hogql.visitor import clone_expr
from posthog.models.team import Team
from posthog.clickhouse.query_tagging import tag_queries
from posthog.client import sync_execute
from posthog.schema import HogQLQueryResponse


def execute_hogql_query(
    query: Union[str, ast.SelectQuery],
    team: Team,
    query_type: str = "hogql_query",
    placeholders: Optional[Dict[str, ast.Expr]] = None,
    workload: Workload = Workload.ONLINE,
    settings: Optional[HogQLSettings] = None,
    default_limit: Optional[int] = None,
) -> HogQLQueryResponse:
    if isinstance(query, ast.SelectQuery):
        select_query = query
        query = None
    else:
        select_query = parse_select(str(query))

    select_query = replace_placeholders(select_query, placeholders)

    if select_query.limit is None:
        # One more "max" of MAX_SELECT_RETURNED_ROWS (100k) in applied in the query printer, overriding this if higher.
        from posthog.hogql.constants import DEFAULT_RETURNED_ROWS

        select_query.limit = ast.Constant(value=default_limit or DEFAULT_RETURNED_ROWS)

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
    clickhouse_sql = print_ast(
        select_query, context=clickhouse_context, dialect="clickhouse", settings=settings or HogQLSettings()
    )

    tag_queries(
        team_id=team.pk,
        query_type=query_type,
        has_joins="JOIN" in clickhouse_sql,
        has_json_operations="JSONExtract" in clickhouse_sql or "JSONHas" in clickhouse_sql,
    )

    results, types = sync_execute(
        clickhouse_sql,
        clickhouse_context.values,
        with_column_types=True,
        workload=workload,
        team_id=team.pk,
        readonly=True,
    )

    return HogQLQueryResponse(
        query=query,
        hogql=hogql,
        clickhouse=clickhouse_sql,
        results=results,
        columns=print_columns,
        types=types,
    )
