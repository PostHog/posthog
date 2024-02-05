from django.conf import settings
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import HogQLException
from posthog.hogql.filters import replace_filters
from posthog.hogql.hogql import translate_hogql
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.hogql.query import create_default_modifiers_for_team
from posthog.hogql_queries.query_runner import get_query_runner
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
        errors=[],
        warnings=[],
        notices=[],
    )

    query_modifiers = create_default_modifiers_for_team(team)

    try:
        if isinstance(query.expr, str):
            context = HogQLContext(team_id=team.pk, modifiers=query_modifiers, debug=query.debug)
            if query.exprSource is not None:
                source_query = get_query_runner(query.exprSource, team).to_query()
                translate_hogql(query.expr, context=context, metadata_source=source_query)
            else:
                translate_hogql(query.expr, context=context)
        elif isinstance(query.select, str):
            context = HogQLContext(
                team_id=team.pk,
                modifiers=query_modifiers,
                enable_select_queries=True,
                debug=query.debug,
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
    except Exception as e:
        response.isValid = False
        if isinstance(e, ValueError):
            response.errors.append(HogQLNotice(message=str(e)))
        elif isinstance(e, HogQLException):
            error = str(e)
            if "mismatched input '<EOF>' expecting" in error:
                error = "Unexpected end of query"
            response.errors.append(HogQLNotice(message=error, start=e.start, end=e.end))
        elif not settings.DEBUG:
            # We don't want to accidentally expose too much data via errors
            response.errors.append(HogQLNotice(message=f"Unexpected {e.__class__.__name__}"))

    return response


def is_valid_view(select_query: ast.SelectQuery | ast.SelectUnionQuery) -> bool:
    if not isinstance(select_query, ast.SelectQuery):
        return False
    for field in select_query.select:
        if not isinstance(field, ast.Alias):
            return False

    return True
