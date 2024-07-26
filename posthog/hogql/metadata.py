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
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import Team
from posthog.schema import HogQLMetadataResponse, HogQLMetadata, HogQLNotice, HogLanguage
from posthog.hogql import ast


def get_hogql_metadata(
    query: HogQLMetadata,
    team: Team,
) -> HogQLMetadataResponse:
    response = HogQLMetadataResponse(
        isValid=True,
        isValidView=False,
        query=query.query,
        errors=[],
        warnings=[],
        notices=[],
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
            create_bytecode(program, supported_functions={"fetch", "posthogCapture"}, args=[], context=context)
        elif query.language == HogLanguage.HOG_QL_EXPR or query.language == HogLanguage.HOG_TEMPLATE:
            node: ast.Expr
            if query.language == HogLanguage.HOG_TEMPLATE:
                node = parse_string_template(query.query)
            else:
                node = parse_expr(query.query)
            if query.sourceQuery is not None:
                source_query = get_query_runner(query=query.sourceQuery, team=team).to_query()
                process_expr_on_table(node, context=context, source_query=source_query)
            else:
                process_expr_on_table(node, context=context)
        elif query.language == HogLanguage.HOG_QL:
            select_ast = parse_select(query.query)
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
        elif not settings.DEBUG:
            # We don't want to accidentally expose too much data via errors
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
    source_query: Optional[ast.SelectQuery | ast.SelectUnionQuery] = None,
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


def is_valid_view(select_query: ast.SelectQuery | ast.SelectUnionQuery) -> bool:
    if isinstance(select_query, ast.SelectQuery):
        for field in select_query.select:
            if not isinstance(field, ast.Alias):
                return False
    elif isinstance(select_query, ast.SelectUnionQuery):
        for select in select_query.select_queries:
            for field in select.select:
                if not isinstance(field, ast.Alias):
                    return False

    return True
