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
    is_valid = True
    error: str | None = None

    try:
        context = HogQLContext(team_id=team.pk)
        if isinstance(query.expr, str):
            translate_hogql(query.expr, context=context)
        elif isinstance(query.select, str):
            print_ast(parse_select(query.select), context=context, dialect="clickhouse")
        else:
            raise ValueError("Either expr or select must be provided")
    except Exception as e:
        is_valid = False
        if isinstance(e, ValueError) or isinstance(e, HogQLException):
            error = str(e)

    if error and "mismatched input '<EOF>' expecting" in error:
        error = "Unexpected end of query"

    return HogQLMetadataResponse(
        isValid=is_valid,
        expr=query.expr,
        select=query.select,
        error=error,
    )
