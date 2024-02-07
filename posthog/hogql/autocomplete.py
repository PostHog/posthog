from typing import cast
from posthog.hogql.filters import replace_filters
from posthog.hogql.parser import parse_select
from posthog.hogql import ast
from posthog.models.team.team import Team
from posthog.schema import (
    HogQLAutocomplete,
    HogQLAutocompleteResponse,
    AutocompleteCompletionItem,
    Kind,
)


def get_hogql_autocomplete(query: HogQLAutocomplete, team: Team) -> HogQLAutocompleteResponse:
    response = HogQLAutocompleteResponse(suggestions=[])

    try:
        select_ast = parse_select(query.select)
        if query.filters:
            select_ast = cast(ast.SelectQuery, replace_filters(select_ast, query.filters, team))
    except Exception:
        pass

    response.suggestions.append(
        AutocompleteCompletionItem(
            insertText="some_field",
            label="some_field",
            kind=Kind.Field,
        )
    )

    return response
