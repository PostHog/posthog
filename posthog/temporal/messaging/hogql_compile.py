from typing import Any

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import prepare_and_print_ast

from posthog.sync import database_sync_to_async_pool


@database_sync_to_async_pool
def compile_hogql_for_streaming(node: ast.SelectQuery, *, team_id: int) -> tuple[str, dict[str, Any]]:
    """Compile a HogQL ``SelectQuery`` to ClickHouse SQL for the streaming HTTP client.

    Backfill workflows in this package run HogQL on a background path that has no
    request-scoped user. They need the activity to behave identically to the previous
    raw-SQL implementation, so property access-control restrictions are explicitly
    bypassed with ``restricted_properties=set()`` — otherwise the printer would call
    ``get_restricted_properties_for_team(team_id, user=None)``, which applies any
    property-level rules and would silently change cohort evaluation results compared
    to the raw-SQL baseline.

    Returns the printed SQL and the parameter dict captured on the printer context.
    """
    hogql_context = HogQLContext(
        team_id=team_id,
        enable_select_queries=True,
        limit_context=LimitContext.COHORT_CALCULATION,
        output_format="JSONEachRow",
        restricted_properties=set(),
    )
    sql, _ = prepare_and_print_ast(node, hogql_context, "clickhouse")
    return sql, hogql_context.values
