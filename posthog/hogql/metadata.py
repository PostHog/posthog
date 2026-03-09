from typing import Optional, Union, cast

from django.conf import settings

from posthog.schema import HogLanguage, HogQLMetadata, HogQLMetadataResponse, HogQLNotice

from posthog.hogql import ast
from posthog.hogql.base import AST
from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database, get_data_warehouse_table_name
from posthog.hogql.database.models import FunctionCallTable, TableNode
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.filters import replace_filters
from posthog.hogql.parser import parse_expr, parse_program, parse_select, parse_string_template
from posthog.hogql.placeholders import find_placeholders, replace_placeholders
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import create_default_modifiers_for_team
from posthog.hogql.variables import replace_variables
from posthog.hogql.visitor import TraversingVisitor, clone_expr

from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import Team
from posthog.models.user import User

from products.data_warehouse.backend.models import ExternalDataSource
from products.data_warehouse.backend.models.external_data_source import get_external_data_source_for_connection
from products.data_warehouse.backend.models.table import DataWarehouseTable


def _prune_database_for_direct_metadata(database: Database, allowed_table_names: set[str]) -> None:
    def prune_node(node: TableNode, chain: list[str]) -> bool:
        full_name = ".".join(chain)

        keep_table = node.table is not None and (
            full_name in allowed_table_names or (len(chain) > 0 and isinstance(node.table, FunctionCallTable))
        )

        pruned_children: dict[str, TableNode] = {}
        for child_name, child in node.children.items():
            if prune_node(child, [*chain, child_name]):
                pruned_children[child_name] = child
        node.children = pruned_children

        return node.name == "root" or keep_table or len(node.children) > 0

    prune_node(database.tables, [])
    database._warehouse_table_names = [name for name in database._warehouse_table_names if name in allowed_table_names]
    database._warehouse_self_managed_table_names = [
        name for name in database._warehouse_self_managed_table_names if name in allowed_table_names
    ]
    database._view_table_names = [name for name in database._view_table_names if name in allowed_table_names]


def get_hogql_metadata(
    query: HogQLMetadata,
    team: Team,
    user: Optional[User] = None,
    hogql_ast: Optional[Union[ast.SelectQuery, ast.SelectSetQuery]] = None,
    clickhouse_prepared_ast: Optional[ast.AST] = None,
    clickhouse_sql: Optional[str] = None,
) -> HogQLMetadataResponse:
    response = HogQLMetadataResponse(
        isValid=True,
        query=query.query,
        errors=[],
        warnings=[],
        notices=[],
        table_names=[],
    )

    query_modifiers = create_default_modifiers_for_team(team, query.modifiers)
    source = get_external_data_source_for_connection(team_id=team.pk, connection_id=query.connectionId)
    if query.connectionId and source is None:
        response.isValid = False
        response.errors = [HogQLNotice(message="Invalid connectionId for this team")]
        return response

    database = None
    if source and source.source_id:
        database = Database.create_for(
            team=team,
            modifiers=query_modifiers,
            direct_query_source_id=str(source.id)
            if source.access_method == ExternalDataSource.AccessMethod.DIRECT
            else None,
        )
        if source.access_method == ExternalDataSource.AccessMethod.DIRECT:
            direct_tables = DataWarehouseTable.raw_objects.filter(
                team_id=team.pk,
                external_data_source_id=source.id,
            ).exclude(deleted=True)
            allowed_table_names = {
                get_data_warehouse_table_name(source, table.name, use_direct_database_names=True)
                for table in direct_tables
            }
            _prune_database_for_direct_metadata(database, allowed_table_names)

    try:
        context = HogQLContext(
            team_id=team.pk,
            user=user,
            database=database,
            modifiers=query_modifiers,
            enable_select_queries=True,
            debug=query.debug or False,
            globals=query.globals,
        )
        if query.language == HogLanguage.HOG:
            program = parse_program(query.query)
            create_bytecode(program, supported_functions={"fetch", "postHogCapture"}, args=[], context=context)
        elif query.language == HogLanguage.HOG_TEMPLATE:
            string = parse_string_template(query.query)
            create_bytecode(string, supported_functions={"fetch", "postHogCapture"}, args=[], context=context)
        elif query.language == HogLanguage.HOG_QL_EXPR:
            node = parse_expr(query.query)
            if query.sourceQuery is not None:
                source_query = get_query_runner(query=query.sourceQuery, team=team).to_query()
                process_expr_on_table(node, context=context, source_query=source_query)
            else:
                process_expr_on_table(node, context=context)
        elif query.language == HogLanguage.HOG_QL:
            if not hogql_ast:
                hogql_ast = parse_select(query.query)
                finder = find_placeholders(hogql_ast)
                if finder.has_filters:
                    hogql_ast = replace_filters(hogql_ast, query.filters, team)
                if query.variables or finder.placeholder_fields or finder.placeholder_expressions:
                    hogql_ast = replace_variables(
                        hogql_ast, list(query.variables.values()) if query.variables else [], team
                    )
                    hogql_ast = cast(ast.SelectQuery, replace_placeholders(hogql_ast, query.globals))

            hogql_table_names = get_table_names(hogql_ast)
            response.table_names = hogql_table_names

            if source and source.access_method == ExternalDataSource.AccessMethod.DIRECT:
                prepare_and_print_ast(
                    clone_expr(hogql_ast),
                    context=context,
                    dialect="postgres",
                )
            else:
                if not clickhouse_sql or not clickhouse_prepared_ast:
                    clickhouse_sql, clickhouse_prepared_ast = prepare_and_print_ast(
                        clone_expr(hogql_ast),
                        context=context,
                        dialect="clickhouse",
                    )

                if clickhouse_prepared_ast:
                    ch_table_names = get_table_names(clickhouse_prepared_ast)
                    response.ch_table_names = ch_table_names
        else:
            raise ValueError(f"Unsupported language: {query.language}")
        response.warnings = context.warnings
        response.notices = context.notices
        response.errors = context.errors
        response.isValid = len(response.errors) == 0
    except Exception as e:
        response.isValid = False
        if isinstance(e, ExposedHogQLError):
            error = str(e)
            if "mismatched input '<EOF>' expecting" in error:
                error = "Unexpected end of query"
            if e.end and e.start and e.end < e.start:
                response.errors.append(HogQLNotice(message=error, start=e.end, end=e.start))
            else:
                response.errors.append(HogQLNotice(message=error, start=e.start, end=e.end))
        elif (
            settings.DEBUG
        ):  # We don't want to accidentally expose too much data via errors, so expose only when debug is enabled
            response.errors.append(HogQLNotice(message=f"Unexpected {e.__class__.__name__}: {str(e)}"))
        else:
            response.errors.append(HogQLNotice(message=f"Unexpected {e.__class__.__name__}"))

    # We add a magic "F'" start prefix to get Antlr into the right parsing mode, subtract it now
    if query.language == HogLanguage.HOG_TEMPLATE:
        for err in response.errors:
            if err.start is not None and err.end is not None and err.start > 0:
                err.start -= 2
                err.end -= 2

    return response


def process_expr_on_table(
    node: ast.Expr,
    context: HogQLContext,
    source_query: Optional[ast.SelectQuery | ast.SelectSetQuery] = None,
):
    try:
        if source_query is not None:
            select_query = cast(ast.SelectQuery, clone_expr(source_query, clear_locations=True))
            select_query.select.append(node)
        else:
            select_query = ast.SelectQuery(select=[node], select_from=ast.JoinExpr(table=ast.Field(chain=["events"])))

        # Nothing to return, we just make sure it doesn't throw
        prepare_and_print_ast(select_query, context, "clickhouse")
    except (NotImplementedError, SyntaxError):
        raise


def get_table_names(select_query: AST) -> list[str]:
    # Don't need types, we're only interested in the table names as passed in
    collector = TableCollector()
    collector.visit(select_query)
    return list(collector.table_names - collector.ctes)


class TableCollector(TraversingVisitor):
    def __init__(self):
        self.table_names = set()
        self.ctes = set()

    def visit_cte(self, node: ast.CTE):
        self.ctes.add(node.name)
        super().visit(node.expr)

    def visit_join_expr(self, node: ast.JoinExpr):
        if isinstance(node.table, ast.Field):
            self.table_names.add(".".join([str(x) for x in node.table.chain]))
        else:
            self.visit(node.table)

        self.visit(node.next_join)
