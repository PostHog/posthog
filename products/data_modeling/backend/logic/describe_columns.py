"""Reads the output columns of a view's query with DESCRIBE, shared by saving a view and materializing it."""

from time import sleep
from typing import TYPE_CHECKING, Optional

from clickhouse_driver.errors import ServerException

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.functions.prompt_jev import PromptJevFinder, is_decision_call
from posthog.hogql.printer import print_prepared_ast
from posthog.hogql.printer.clickhouse import ClickHousePrinter
from posthog.hogql.query import TRANSIENT_S3_ERROR_RETRY_DELAY_SECONDS, HogQLQueryExecutor
from posthog.hogql.resolver_utils import extract_select_queries
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.client.execute import ClickHouseExternalTable
from posthog.errors import CHQueryErrorS3Error, CHQueryErrorS3FileChangedDuringRead
from posthog.models.event.new_events_schema import events_route_scope
from posthog.models.team import Team

from products.data_modeling.backend.facade.contracts import DescribedColumn

if TYPE_CHECKING:
    from posthog.models.user import User

THERE_IS_NO_COLUMN_ERROR_CODE = 8


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


_IN_SUBQUERY_OPS = (
    ast.CompareOperationOp.In,
    ast.CompareOperationOp.NotIn,
    ast.CompareOperationOp.GlobalIn,
    ast.CompareOperationOp.GlobalNotIn,
)


class _DowngradeGlobalIn(CloningVisitor):
    def __init__(self) -> None:
        super().__init__(clear_types=False, clear_locations=False)
        self.downgraded = False

    def visit_compare_operation(self, node: ast.CompareOperation) -> ast.CompareOperation:
        cloned = super().visit_compare_operation(node)
        if cloned.op in _LOCAL_COMPARE_OPS:
            cloned.op = _LOCAL_COMPARE_OPS[cloned.op]
            self.downgraded = True
        return cloned


class _ZeroRowJevPlanning(TraversingVisitor):
    def visit_select_query(self, node: ast.SelectQuery) -> None:
        super().visit_select_query(node)
        if any(_is_jev_column(column) for column in node.select):
            _limit_to_zero_rows(node)

    def visit_compare_operation(self, node: ast.CompareOperation) -> None:
        super().visit_compare_operation(node)
        if node.op in _IN_SUBQUERY_OPS and isinstance(node.right, ast.SelectQuery | ast.SelectSetQuery):
            _limit_to_zero_rows(node.right)


def _limit_to_zero_rows(select_query: ast.SelectQuery | ast.SelectSetQuery) -> None:
    for branch in extract_select_queries(select_query):
        branch.limit = ast.Constant(value=0)
        branch.offset = None


def print_describe_variant(
    prepared_query: ast.SelectQuery | ast.SelectSetQuery, context: HogQLContext, settings: HogQLGlobalSettings
) -> str:
    downgrade = _DowngradeGlobalIn()
    downgraded = downgrade.visit(prepared_query)
    if downgrade.downgraded:
        _keep_output_names(downgraded, prepared_query, context)
    return print_prepared_ast(downgraded, context=context, dialect="clickhouse", settings=settings, stack=[])


def _keep_output_names(
    downgraded: ast.SelectQuery | ast.SelectSetQuery,
    prepared_query: ast.SelectQuery | ast.SelectSetQuery,
    context: HogQLContext,
) -> None:
    output = _output_select(downgraded)
    untouched_names = _output_names(_output_select(prepared_query), context)
    downgraded_names = _output_names(output, context)
    output.select = [
        column if downgraded_name == untouched_name else ast.Alias(alias=untouched_name, expr=column)
        for column, untouched_name, downgraded_name in zip(output.select, untouched_names, downgraded_names)
    ]


def _output_select(query: ast.SelectQuery | ast.SelectSetQuery) -> ast.SelectQuery:
    while isinstance(query, ast.SelectSetQuery):
        query = query.initial_select_query
    return query


def _output_names(output: ast.SelectQuery, context: HogQLContext) -> list[str]:
    return ClickHousePrinter(context=context, stack=[output]).select_column_names(output)


def _is_jev_column(column: ast.Expr) -> bool:
    return isinstance(column, ast.Alias) and isinstance(column.expr, ast.Call) and is_decision_call(column.expr.name)


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
    zero_row_query = clone_expr(select_query)
    _ZeroRowJevPlanning().visit(zero_row_query)
    planned_query, jev_tables = HogQLQueryExecutor(
        query=zero_row_query,
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
    try:
        return _run_describe(sql, context, team, settings, external_tables)
    except (CHQueryErrorS3Error, CHQueryErrorS3FileChangedDuringRead):
        sleep(TRANSIENT_S3_ERROR_RETRY_DELAY_SECONDS)
        return _run_describe(sql, context, team, settings, external_tables)


def _run_describe(
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
