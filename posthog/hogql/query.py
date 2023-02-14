from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Extra

from posthog.clickhouse.client.connection import Workload
from posthog.hogql import ast
from posthog.hogql.hogql import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import assert_no_placeholders, replace_placeholders
from posthog.hogql.printer import print_ast
from posthog.hogql.resolver import resolve_symbols
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
        select_query.limit = ast.Constant(value=1000)

    hogql_context = HogQLContext(select_team_id=team.pk)
    resolve_symbols(select_query)
    clickhouse = print_ast(select_query, hogql_context, "clickhouse")
    hogql = print_ast(select_query, hogql_context, "hogql")

    results, types = insight_sync_execute(
        clickhouse,
        hogql_context.values,
        with_column_types=True,
        query_type=query_type,
        workload=workload,
    )
    print_columns = [print_ast(col, HogQLContext(), "hogql") for col in select_query.select]
    return HogQLQueryResponse(
        query=query,
        hogql=hogql,
        clickhouse=clickhouse,
        results=results,
        columns=print_columns,
        types=types,
    )
