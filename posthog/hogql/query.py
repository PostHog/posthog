from typing import Any, List, Optional, Union

from pydantic import BaseModel, Extra

from posthog.clickhouse.client.connection import Workload
from posthog.hogql import ast
from posthog.hogql.hogql import HogQLContext
from posthog.hogql.parser import parse_statement
from posthog.hogql.printer import print_ast, quick_print_hogql
from posthog.models import Team
from posthog.queries.insight import insight_sync_execute


class QueryResult(BaseModel):
    class Config:
        extra = Extra.forbid

    query: Optional[str] = None
    hogql: Optional[str] = None
    clickhouse: Optional[str] = None
    results: Optional[List[Any]] = None
    types: Optional[List[Any]] = None
    columns: Optional[List[Any]] = None


def execute_hogql_query(
    query: Union[str, ast.SelectQuery],
    team: Team,
    query_type: str = "unlabeled_hogql_query",
    workload: Workload = Workload.OFFLINE,
) -> QueryResult:
    if isinstance(query, ast.SelectQuery):
        select_query = query
        query = None
    else:
        select_query = parse_statement(str(query))

    if select_query.limit is None:
        select_query.limit = 1000

    hogql_context = HogQLContext(select_team_id=team.pk)
    clickhouse = print_ast(select_query, [], hogql_context, "clickhouse")
    hogql = print_ast(select_query, [], hogql_context, "hogql")

    results, types = insight_sync_execute(
        clickhouse,
        hogql_context.values,
        with_column_types=True,
        query_type=query_type,
        workload=workload,
    )
    print_columns = [quick_print_hogql(col) for col in select_query.select]
    return QueryResult(
        query=query,
        hogql=hogql,
        clickhouse=clickhouse,
        results=results,
        columns=print_columns,
        types=types,
    )
