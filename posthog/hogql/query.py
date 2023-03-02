from typing import Dict, List, Optional, Union, cast

from pydantic import BaseModel, Extra

from posthog.clickhouse.client.connection import Workload
from posthog.hogql import ast
from posthog.hogql.constants import DEFAULT_RETURNED_ROWS
from posthog.hogql.hogql import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import assert_no_placeholders, replace_placeholders
from posthog.hogql.printer import prepare_ast_for_printing, print_ast, print_prepared_ast
from posthog.models import Team
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

    # Make a copy for hogql printing later. we don't want it to contain joined SQL tables for example

    hogql_context = HogQLContext(select_team_id=team.pk, using_person_on_events=team.person_on_events_querying_enabled)
    clickhouse = print_ast(select_query, hogql_context, "clickhouse")

    select_query_hogql = cast(ast.SelectQuery, prepare_ast_for_printing(select_query, "hogql"))
    hogql = print_prepared_ast(select_query_hogql, hogql_context, "hogql")

    results, types = insight_sync_execute(
        clickhouse,
        hogql_context.values,
        with_column_types=True,
        query_type=query_type,
        workload=workload,
    )
    print_columns = []
    for node in select_query_hogql.select:
        if isinstance(node, ast.Alias):
            print_columns.append(node.alias)
        else:
            print_columns.append(
                print_ast(node=node, context=hogql_context, dialect="hogql", stack=[select_query_hogql])
            )

    return HogQLQueryResponse(
        query=query,
        hogql=hogql,
        clickhouse=clickhouse,
        results=results,
        columns=print_columns,
        types=types,
    )
