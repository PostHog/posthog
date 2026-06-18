from typing import Any, Optional

from django.db import models
from django.db.models.functions.comparison import Coalesce

from posthog.schema import AutocompleteCompletionItem, HogQLAutocomplete, HogQLAutocompleteResponse, QueryTiming

from common.hogql.autocomplete import (
    AutocompleteCompletionItem as CommonAutocompleteCompletionItem,
    HogQLAutocompleteResponse as CommonHogQLAutocompleteResponse,
    get_hogql_autocomplete as get_common_hogql_autocomplete,
)
from common.hogql.database.database import Database
from common.hogql.dependencies import AutocompletePropertyDefinition, HogQLAutocompleteProvider

from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models.team.team import Team
from posthog.models.user import User

from products.event_definitions.backend.models.property_definition import PropertyDefinition
from products.product_analytics.backend.models.insight_variable import InsightVariable


class PostHogAutocompleteProvider(HogQLAutocompleteProvider):
    def capture_exception(self, exception: Exception) -> None:
        capture_exception(exception)

    def source_query_to_select(self, source_query: Any, team: Team):
        return get_query_runner(query=source_query, team=team).to_query()

    def list_property_definitions(
        self,
        *,
        team: Team,
        property_type: int,
        match: str,
        limit: int,
    ) -> tuple[list[AutocompletePropertyDefinition], bool]:
        property_query = PropertyDefinition.objects.alias(
            effective_project_id=Coalesce("project_id", "team_id", output_field=models.BigIntegerField())
        ).filter(
            effective_project_id=team.project_id,
            name__contains=match,
            type=property_type,
        )

        total_property_count = property_query.count()
        properties = property_query[:limit].values("name", "property_type")
        return (
            [
                AutocompletePropertyDefinition(name=str(prop["name"]), property_type=prop["property_type"])
                for prop in properties
            ],
            total_property_count > limit,
        )

    def list_insight_variable_code_names(self, *, team: Team) -> list[str]:
        return [
            variable.code_name
            for variable in InsightVariable.objects.filter(team_id=team.pk).order_by("name")
            if variable.code_name
        ]


def _convert_suggestion(suggestion: CommonAutocompleteCompletionItem) -> AutocompleteCompletionItem:
    return AutocompleteCompletionItem(
        insertText=suggestion.insertText,
        label=suggestion.label,
        kind=suggestion.kind,
        detail=suggestion.detail,
    )


def _convert_response(response: CommonHogQLAutocompleteResponse) -> HogQLAutocompleteResponse:
    return HogQLAutocompleteResponse(
        suggestions=[_convert_suggestion(suggestion) for suggestion in response.suggestions],
        incomplete_list=response.incomplete_list,
        timings=[QueryTiming(k=str(timing["k"]), t=float(timing["t"])) for timing in response.timings or []],
    )


def get_hogql_autocomplete(
    query: HogQLAutocomplete,
    team: Team,
    user: Optional[User] = None,
    database_arg: Optional[Database] = None,
) -> HogQLAutocompleteResponse:
    response = get_common_hogql_autocomplete(
        query=query,
        team=team,
        user=user,
        database_arg=database_arg,
        autocomplete_provider=PostHogAutocompleteProvider(),
    )
    return _convert_response(response)
