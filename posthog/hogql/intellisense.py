from posthog.models.team.team import Team
from posthog.schema import (
    HogQLIntelliSense,
    HogQLIntelliSenseResponse,
    IntelliSenseCompletionItem,
    Kind,
)


def get_hogql_intellisense(query: HogQLIntelliSense, team: Team) -> HogQLIntelliSenseResponse:
    response = HogQLIntelliSenseResponse(suggestions=[])

    response.suggestions.append(
        IntelliSenseCompletionItem(
            insertText="some_field",
            label="some_field",
            kind=Kind.Field,
        )
    )

    return response
