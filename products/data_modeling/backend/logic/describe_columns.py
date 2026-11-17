"""Reads the output columns of a view's query with DESCRIBE, shared by saving a view and materializing it."""

from typing import TYPE_CHECKING, Optional

from clickhouse_driver.errors import ServerException

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.functions.prompt_jev import PromptJevFinder
from posthog.hogql.printer import print_prepared_ast
from posthog.hogql.query import HogQLQueryExecutor
from posthog.hogql.visitor import CloningVisitor

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.client.execute import ClickHouseExternalTable
from posthog.dataclasses import frozen
from posthog.models.event.new_events_schema import events_route_scope
from posthog.models.team import Team

if TYPE_CHECKING:
    from posthog.models.user import User

THERE_IS_NO_COLUMN_ERROR_CODE = 8


@frozen
class DescribedColumn:
    name: str
    ch_type: str


# ClickHouse builds every GLOBAL IN subquery as a temporary table while it plans a query, and
# DESCRIBE plans the query too, so the schema probe scans the source tables just to return column
# types. The probe therefore prints a copy of the query with GLOBAL IN downgraded to plain IN and
# runs with the two settings that would add GLOBAL back pinned off (the cluster profile sets
# distributed_product_mode=global). Joins keep their GLOBAL prefix: the resolver adds it to
# events-to-S3 join chains to work around a ClickHouse bug, not for cost. The materialization query
# itself is printed from the untouched AST.
DESCRIBE_QUERY_SETTINGS = {"distributed_product_mode": "allow", "prefer_global_in_and_join": "0"}

_LOCAL_COMPARE_OPS = {
    ast.CompareOperationOp.GlobalIn: ast.CompareOperationOp.In,
    ast.CompareOperationOp.GlobalNotIn: ast.CompareOperationOp.NotIn,
}


class _DowngradeGlobalIn(CloningVisitor):
    def __init__(self) -> None:
        super().__init__(clear_types=False, clear_locations=False)

    def visit_compare_operation(self, node: ast.CompareOperation) -> ast.CompareOperation:
        cloned = super().visit_compare_operation(node)
        cloned.op = _LOCAL_COMPARE_OPS.get(cloned.op, cloned.op)
        return cloned


def print_describe_variant(
    prepared_query: ast.SelectQuery | ast.SelectSetQuery, context: HogQLContext, settings: HogQLGlobalSettings
) -> str:
    downgraded = _DowngradeGlobalIn().visit(prepared_query)
    return print_prepared_ast(downgraded, context=context, dialect="clickhouse", settings=settings, stack=[])


def describe_ast_settings(settings: HogQLGlobalSettings) -> dict[str, str]:
    return {
        name: str(value)
        for name, value in {
            "max_ast_elements": settings.max_ast_elements,
            "max_expanded_ast_elements": settings.max_expanded_ast_elements,
        }.items()
        if value is not None
    }


def describe_query_columns(
    select_query: ast.SelectQuery | ast.SelectSetQuery,
    *,
    team: Team,
    user: Optional["User"],
    bypass_warehouse_access_control: bool,
) -> list[DescribedColumn]:
    """The query's output columns, read without running the query."""
    context = HogQLContext(team_id=team.pk, user=user, bypass_warehouse_access_control=bypass_warehouse_access_control)
    jev_external_tables: list[ClickHouseExternalTable] = []
    if PromptJevFinder.contains(select_query):
        select_query, jev_external_tables = _plan_prompt_jev(select_query, context, team)

    executor = HogQLQueryExecutor(query=select_query, team=team, user=user, query_type="HogQLQuery", context=context)
    untouched_sql, printed_context = executor.generate_clickhouse_sql()
    prepared_query = executor.clickhouse_prepared_ast
    settings = executor.clickhouse_settings
    if not isinstance(prepared_query, ast.SelectQuery | ast.SelectSetQuery) or settings is None:
        return []

    external_tables = [*printed_context.external_tables.values(), *jev_external_tables]
    ast_settings = describe_ast_settings(settings)
    describe_variant_sql = print_describe_variant(prepared_query, printed_context, settings)
    try:
        return _describe(
            describe_variant_sql,
            printed_context,
            team,
            {**DESCRIBE_QUERY_SETTINGS, **ast_settings},
            external_tables,
        )
    except ServerException as error:
        if error.code != THERE_IS_NO_COLUMN_ERROR_CODE:
            raise
        return _describe(untouched_sql, printed_context, team, ast_settings, external_tables)


def _plan_prompt_jev(
    select_query: ast.SelectQuery | ast.SelectSetQuery, context: HogQLContext, team: Team
) -> tuple[ast.SelectQuery | ast.SelectSetQuery, list[ClickHouseExternalTable]]:
    planned_query, jev_tables = HogQLQueryExecutor(
        query=select_query,
        team=team,
        user=context.user,
        bypass_warehouse_access_control=context.bypass_warehouse_access_control,
    ).plan_prompt_jev()
    context.database = Database.create_for(
        team=team,
        user=context.user,
        bypass_warehouse_access_control=context.bypass_warehouse_access_control,
    )
    for table in jev_tables:
        table.register(context)
    return planned_query, list(context.external_tables.values())


def _describe(
    sql: str,
    context: HogQLContext,
    team: Team,
    settings: dict[str, str],
    external_tables: list[ClickHouseExternalTable],
) -> list[DescribedColumn]:
    with events_route_scope(HogQLQueryModifiers(useNewEventsSchema=context.uses_new_events_schema())):
        # nosemgrep: clickhouse-fstring-param-audit - sql is printed by the HogQL printer, values stay parameterized
        rows = sync_execute(
            f"DESCRIBE TABLE ({sql})",
            context.values,
            settings=settings,
            workload=context.workload or Workload.DEFAULT,
            team_id=team.pk,
            readonly=True,
            external_tables=external_tables or None,
        )
    return [DescribedColumn(name=str(row[0]), ch_type=str(row[1])) for row in rows]
