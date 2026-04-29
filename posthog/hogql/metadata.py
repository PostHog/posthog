from typing import Literal, Optional, Union, cast

from django.conf import settings

from pydantic import BaseModel

from posthog.schema import HogLanguage, HogQLMetadata, HogQLMetadataResponse, HogQLNotice, HogQLQuery

from posthog.hogql import ast
from posthog.hogql.base import AST
from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.direct_connection import get_direct_connection_source
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.filters import replace_filters
from posthog.hogql.metadata_heuristics import run_metadata_heuristics
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_expr, parse_program, parse_select, parse_string_template
from posthog.hogql.placeholders import find_placeholders, replace_placeholders
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.variables import replace_variables
from posthog.hogql.visitor import TraversingVisitor, clone_expr

from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import Team
from posthog.models.user import User


def get_hogql_metadata(
    query: HogQLMetadata,
    team: Team,
    user: Optional[User] = None,
    hogql_ast: Optional[Union[ast.SelectQuery, ast.SelectSetQuery]] = None,
    prepared_ast: Optional[ast.AST] = None,  # precached
    printed_sql: Optional[str] = None,  # precached
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
    source = get_direct_connection_source(team, query.connectionId)
    if query.connectionId and source is None:
        response.isValid = False
        response.errors = [HogQLNotice(message="Invalid connectionId for this team")]
        return response

    database = None
    if source:
        database = Database.create_for(
            team=team,
            user=user,
            modifiers=query_modifiers,
            connection_id=str(source.id),
        )

    heuristic_warnings: list[HogQLNotice] = []
    context: Optional[HogQLContext] = None

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
                    hogql_ast = replace_filters(hogql_ast, query.filters, team, database=database)
                if query.variables or finder.placeholder_fields or finder.placeholder_expressions:
                    hogql_ast = replace_variables(
                        hogql_ast, list(query.variables.values()) if query.variables else [], team
                    )
                    hogql_ast = cast(ast.SelectQuery, replace_placeholders(hogql_ast, query.globals))

            heuristic_warnings.extend(run_metadata_heuristics(hogql_ast))
            hogql_table_names = get_table_names(hogql_ast)
            response.table_names = hogql_table_names

            if not printed_sql or not prepared_ast:
                printed_sql, prepared_ast = prepare_and_print_ast(
                    clone_expr(hogql_ast),
                    context=context,
                    dialect="postgres" if source else "clickhouse",
                )

            if prepared_ast:
                response.ch_table_names = get_table_names(prepared_ast)
        else:
            raise ValueError(f"Unsupported language: {query.language}")
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
    finally:
        if context is not None:
            response.warnings = [*context.warnings, *heuristic_warnings]
            response.notices = context.notices
            if response.errors:
                response.errors = [*context.errors, *response.errors]
            else:
                response.errors = context.errors
            response.isValid = len(response.errors) == 0

    # We add a magic "F'" start prefix to get Antlr into the right parsing mode, subtract it now
    if query.language == HogLanguage.HOG_TEMPLATE:
        for err in response.errors:
            if err.start is not None and err.end is not None and err.start > 0:
                err.start -= 2
                err.end -= 2

    return response


def enrich_hogql_validation_error(
    query: BaseModel | None,
    team: Team,
    user: Optional[User],
    original_detail: str,
) -> tuple[str, dict | None]:
    """When a HogQLQuery fails, run it through metadata resolution to collect
    structured error positions, table references, and any fix hints. Returns a
    (possibly enriched) detail string and a dict suitable for exceptions_hog's
    ``extra`` attribute — or ``(original_detail, None)`` when enrichment isn't
    applicable or fails.
    """
    if not isinstance(query, HogQLQuery) or not query.query:
        return original_detail, None

    try:
        metadata = get_hogql_metadata(
            query=HogQLMetadata(
                kind="HogQLMetadata",
                language=HogLanguage.HOG_QL,
                query=query.query,
                modifiers=query.modifiers,
                filters=query.filters,
                connectionId=query.connectionId,
            ),
            team=team,
            user=user,
        )
    except Exception:
        return original_detail, None

    lines: list[str] = [original_detail]

    for notice in [*metadata.errors, *metadata.warnings, *metadata.notices]:
        if notice.fix and notice.fix not in lines:
            lines.append(f"Hint: {notice.fix}")

    if metadata.table_names:
        lines.append(f"Tables referenced: {', '.join(metadata.table_names)}")

    extra = {"hogql_metadata": metadata.model_dump(mode="json", exclude_none=True)}
    return "\n".join(lines), extra


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
        dialect: Literal["clickhouse", "postgres"] = (
            "postgres" if getattr(context.database, "_connection_id", None) else "clickhouse"
        )
        prepare_and_print_ast(select_query, context, dialect)
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
