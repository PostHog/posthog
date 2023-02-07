from typing import Union

from posthog.clickhouse.client.connection import Workload
from posthog.hogql import ast
from posthog.hogql.hogql import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast, quick_print_hogql
from posthog.models import Team
from posthog.queries.insight import insight_sync_execute
from posthog.schema import HogQLQueryResponse


def execute_hogql_query(
    query: Union[str, ast.SelectQuery],
    team: Team,
    query_type: str = "unlabeled_hogql_query",
    workload: Workload = Workload.OFFLINE,
) -> HogQLQueryResponse:
    if isinstance(query, ast.SelectQuery):
        select_query = query
        query = None
    else:
        select_query = parse_select(str(query))

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
    return HogQLQueryResponse(
        query=query,
        hogql=hogql,
        clickhouse=clickhouse,
        results=results,
        columns=print_columns,
        types=types,
    )
