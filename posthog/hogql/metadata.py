from typing import Optional, cast

from django.conf import settings

from posthog.hogql.bytecode import create_bytecode
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.filters import replace_filters
from posthog.hogql.parser import parse_select, parse_program, parse_expr, parse_string_template
from posthog.hogql.printer import print_ast
from posthog.hogql.query import create_default_modifiers_for_team
from posthog.hogql.visitor import clone_expr
from posthog.models import Team
from posthog.schema import HogQLMetadataResponse, HogQLMetadata, HogQLNotice
from posthog.hogql import ast


def get_hogql_metadata(
    query: HogQLMetadata,
    team: Team,
) -> HogQLMetadataResponse:
    response = HogQLMetadataResponse(
        isValid=True,
        isValidView=False,
        inputExpr=query.expr,
        inputSelect=query.select,
        inputTemplate=query.template,
        inputProgram=query.program,
        errors=[],
        warnings=[],
        notices=[],
    )

    query_modifiers = create_default_modifiers_for_team(team)

    try:
        if isinstance(query.program, str):
            program = parse_program(query.program)
            create_bytecode(program, supported_functions={"fetch"}, args=[])
        else:
            if isinstance(query.expr, str) or isinstance(query.template, str):
                context = HogQLContext(
                    team_id=team.pk, modifiers=query_modifiers, debug=query.debug or False, enable_select_queries=True
                )
                node: ast.Expr
                if query.template is not None:
                    node = parse_string_template(query.template)
                elif query.expr is not None:
                    node = parse_expr(query.expr)
                else:
                    raise ValueError("Either expr or template must be provided")
                if query.exprSource is not None:
                    process_expr_on_table(node, context=context, source_query=parse_select(query.exprSource))
                else:
                    process_expr_on_table(node, context=context)
            elif isinstance(query.select, str):
                context = HogQLContext(
                    team_id=team.pk,
                    modifiers=query_modifiers,
                    enable_select_queries=True,
                    debug=query.debug or False,
                )
                select_ast = parse_select(query.select)
                if query.filters:
                    select_ast = replace_filters(select_ast, query.filters, team)
                _is_valid_view = is_valid_view(select_ast)
                response.isValidView = _is_valid_view
                print_ast(
                    select_ast,
                    context=context,
                    dialect="clickhouse",
                )
            else:
                raise ValueError("Either expr or select must be provided")
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
        elif not settings.DEBUG:
            # We don't want to accidentally expose too much data via errors
            response.errors.append(HogQLNotice(message=f"Unexpected {e.__class__.__name__}"))

    # We add a magic "F'" start prefix to get Antlr into the right parsing mode, subtract it now
    if query.template is not None:
        for err in response.errors:
            if err.start is not None and err.end is not None and err.start > 0:
                err.start -= 2
                err.end -= 2

    return response


def process_expr_on_table(
    node: ast.Expr,
    context: HogQLContext,
    source_query: Optional[ast.SelectQuery | ast.SelectUnionQuery] = None,
    source_table: Optional[str] = None,
    source_table_alias: Optional[str] = None,
) -> str:
    try:
        if source_query is not None:
            select_query = cast(ast.SelectQuery, clone_expr(source_query, clear_locations=True))
            select_query.select.append(node)
        else:
            select_query = ast.SelectQuery(
                select=[node], select_from=ast.JoinExpr(table=ast.Field(chain=[source_table or "events"]))
            )
            if (
                source_table_alias is not None
                and isinstance(select_query, ast.SelectQuery)
                and isinstance(select_query.select_from, ast.JoinExpr)
            ):
                select_query.select_from.alias = source_table_alias

        return print_ast(select_query, context, "clickhouse")
    except (NotImplementedError, SyntaxError):
        raise


def is_valid_view(select_query: ast.SelectQuery | ast.SelectUnionQuery) -> bool:
    if not isinstance(select_query, ast.SelectQuery):
        return False
    for field in select_query.select:
        if not isinstance(field, ast.Alias):
            return False

    return True
