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
        if isinstance(query.expr, str):
            context = HogQLContext(team_id=team.pk)
            translate_hogql(query.expr, context=context)
        elif isinstance(query.select, str):
            context = HogQLContext(team_id=team.pk, enable_select_queries=True)
            print_ast(parse_select(query.select), context=context, dialect="clickhouse")
        else:
            raise ValueError("Either expr or select must be provided")
    except Exception as e:
        is_valid = False
        if isinstance(e, ValueError):
            error = str(e)
        elif isinstance(e, HogQLException):
            error = f"[{e.start}:{e.stop}] {str(e)}"
        else:
            # We don't want to accidentally expose too much data via errors
            error = f"Unexpected f{e.__class__.__name__}"

    if error and "mismatched input '<EOF>' expecting" in error:
        error = "Unexpected end of query"

    return HogQLMetadataResponse(
        isValid=is_valid,
        expr=query.expr,
        select=query.select,
        error=error,
    )
