from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import HogQLException
from posthog.hogql.hogql import translate_hogql
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.models import Team
from posthog.schema import HogQLMetadataResponse, HogQLMetadata


def get_hogql_metadata(
    query: HogQLMetadata,
    team: Team,
) -> HogQLMetadataResponse:
    response = HogQLMetadataResponse(
        isValid=True,
        inputExpr=query.expr,
        inputSelect=query.select,
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
    except Exception as e:
        response.isValid = False
        if isinstance(e, ValueError):
            response.error = str(e)
        elif isinstance(e, HogQLException):
            response.error = str(e)
            response.errorStart = e.start
            response.errorEnd = e.end
        else:
            # We don't want to accidentally expose too much data via errors
            response.error = f"Unexpected f{e.__class__.__name__}"

    if response.error and "mismatched input '<EOF>' expecting" in response.error:
        response.error = "Unexpected end of query"

    return response
