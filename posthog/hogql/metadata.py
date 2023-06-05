from posthog.hogql.errors import HogQLException
from posthog.hogql.parser import parse_select, parse_expr
from posthog.schema import HogQLMetadataResponse, HogQLMetadata


def get_hogql_metadata(
    query: HogQLMetadata,
) -> HogQLMetadataResponse:
    is_valid = True
    error: str | None = None

    try:
        if isinstance(query.expr, str):
            parse_expr(query.expr)
        elif isinstance(query.select, str):
            parse_select(query.select)
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
