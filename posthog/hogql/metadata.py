from typing import Optional, cast

from django.conf import settings

from posthog.schema import HogLanguage, HogQLMetadata, HogQLMetadataResponse, HogQLNotice, QueryIndexUsage

from posthog.hogql import ast
from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.filters import replace_filters
from posthog.hogql.parser import parse_expr, parse_program, parse_select, parse_string_template
from posthog.hogql.placeholders import find_placeholders, replace_placeholders
from posthog.hogql.printer import print_ast
from posthog.hogql.query import create_default_modifiers_for_team
from posthog.hogql.variables import replace_variables
from posthog.hogql.visitor import TraversingVisitor, clone_expr

from posthog.clickhouse.explain import execute_explain_get_index_use
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import Team


def get_hogql_metadata(
    query: HogQLMetadata,
    team: Team,
) -> HogQLMetadataResponse:
    response = HogQLMetadataResponse(
        isValid=True,
        query=query.query,
        errors=[],
        warnings=[],
        notices=[],
        table_names=[],
    )

    query_modifiers = create_default_modifiers_for_team(team)

    try:
        context = HogQLContext(
            team_id=team.pk,
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
            select_ast = parse_select(query.query)
            finder = find_placeholders(select_ast)
            if finder.has_filters:
                select_ast = replace_filters(select_ast, query.filters, team)
            if query.variables:
                select_ast = replace_variables(select_ast, list(query.variables.values()), team)
            if finder.placeholder_fields or finder.placeholder_expressions:
                select_ast = cast(ast.SelectQuery, replace_placeholders(select_ast, query.globals))

            table_names = get_table_names(select_ast)
            response.table_names = table_names

            clickhouse_sql = print_ast(
                select_ast,
                context=context,
                dialect="clickhouse",
            )

            if context.errors:
                response.isUsingIndices = QueryIndexUsage.UNDECISIVE
            else:
                response.isUsingIndices = execute_explain_get_index_use(clickhouse_sql, context)
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
        print_ast(select_query, context, "clickhouse")
    except (NotImplementedError, SyntaxError):
        raise


def get_table_names(select_query: ast.SelectQuery | ast.SelectSetQuery) -> list[str]:
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
