from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import HogQLException
from posthog.hogql.hogql import translate_hogql
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.models import Team
from posthog.schema import HogQLMetadataResponse, HogQLMetadata, HogQLNotice


def get_hogql_metadata(
    query: HogQLMetadata,
    team: Team,
) -> HogQLMetadataResponse:
    response = HogQLMetadataResponse(
        isValid=True,
        inputExpr=query.expr,
        inputSelect=query.select,
        errors=[],
        warnings=[],
        notices=[],
    )

    try:
        if isinstance(query.expr, str):
            context = HogQLContext(team_id=team.pk)
            translate_hogql(query.expr, context=context)
        elif isinstance(query.select, str):
            context = HogQLContext(team_id=team.pk, enable_select_queries=True)
            print_ast(parse_select(query.select), context=context, dialect="clickhouse")
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
        else:
            # We don't want to accidentally expose too much data via errors
            response.errors.append(HogQLNotice(message=f"Unexpected f{e.__class__.__name__}"))

    return response
