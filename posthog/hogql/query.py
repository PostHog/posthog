from typing import Any, Dict, Optional, Union

from pydantic import BaseModel, Extra

from posthog.clickhouse.client.connection import Workload
from posthog.hogql import ast
from posthog.hogql.hogql import HogQLContext, translate_ast
from posthog.hogql.parser import parse_statement
from posthog.models import Team
from posthog.queries.insight import insight_sync_execute


class QueryResult(BaseModel):
    class Config:
        extra = Extra.forbid

    query: Optional[str] = None
    parsed: bool
    clickhouse_sql: Optional[str] = None
    results: Optional[Any] = None
    types: Optional[Any] = None
    ast: Optional[Dict] = None
    error: Optional[str] = None


def execute_hogql_query(
    query: Union[str, ast.SelectQuery],
    team: Team,
    query_type: str = "unlabeled_hogql_query",
    workload: Workload = Workload.OFFLINE,
) -> QueryResult:
    try:
        if isinstance(query, ast.SelectQuery):
            ast_node = query
            query = None
        else:
            ast_node = parse_statement(str(query))
        hogql_context = HogQLContext(select_team_id=team.pk)
        clickhouse_sql = translate_ast(ast_node, [], hogql_context)
        results, types = insight_sync_execute(
            clickhouse_sql,
            hogql_context.values,
            with_column_types=True,
            query_type=query_type,
            workload=workload,
        )
        return QueryResult(
            query=query,
            parsed=True,
            clickhouse_sql=clickhouse_sql,
            results=results,
            types=types,
            ast={"select": ast_node.dict()},
        )
    except Exception as e:
        return QueryResult(
            query=query,
            parsed=False,
            error=str(e),
        )
