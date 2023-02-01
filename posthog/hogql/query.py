from typing import Any, Dict, Optional

from pydantic import BaseModel, Extra

from posthog.clickhouse.client.connection import Workload
from posthog.hogql.hogql import HogQLContext, translate_hogql
from posthog.hogql.parser import parse_statement
from posthog.queries.insight import insight_sync_execute


class QueryResult(BaseModel):
    class Config:
        extra = Extra.forbid

    query: str
    parsed: bool
    clickhouse_sql: Optional[str] = None
    results: Optional[Any] = None
    types: Optional[Any] = None
    ast: Optional[Dict] = None
    error: Optional[str] = None


def execute_hogql_query(query, team) -> QueryResult:
    try:
        ast_node = parse_statement(query)
        hogql_context = HogQLContext(select_team_id=team.pk)
        clickhouse_sql = translate_hogql(query, hogql_context)
        results, types = insight_sync_execute(
            clickhouse_sql,
            hogql_context.values,
            with_column_types=True,
            query_type="hogql_query",
            workload=Workload.ONLINE,
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
