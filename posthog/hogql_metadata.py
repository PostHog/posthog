from typing import Any

from django.conf import settings

from posthog.schema import (
    HogQLMetadata,
    HogQLMetadataResponse as SchemaHogQLMetadataResponse,
)

from common.hogql import ast
from common.hogql.dependencies import DirectConnectionResolution, HogQLMetadataProvider
from common.hogql.direct_connection import resolve_database_for_connection
from common.hogql.metadata import (
    enrich_hogql_validation_error as enrich_common_hogql_validation_error,
    get_hogql_metadata as get_common_hogql_metadata,
)
from common.hogql.models import HogQLMetadataRequest, HogQLMetadataResponse

from posthog.hogql_queries.query_runner import get_query_runner
from posthog.hogql_variables import PostHogVariableProvider
from posthog.models import Team
from posthog.models.user import User


class PostHogMetadataProvider(PostHogVariableProvider, HogQLMetadataProvider):
    @property
    def debug_errors(self) -> bool:
        return settings.DEBUG

    def source_query_to_select(self, source_query: Any, team: Team) -> ast.SelectQuery | ast.SelectSetQuery:
        return get_query_runner(query=source_query, team=team).to_query()

    def resolve_database_for_connection(
        self,
        *,
        team: Team,
        connection_id: str | None,
        user: User | None,
        modifiers: Any,
    ) -> DirectConnectionResolution:
        try:
            source, database = resolve_database_for_connection(
                team,
                connection_id,
                user=user,
                modifiers=modifiers,
                error_factory=ValueError,
            )
        except ValueError as error:
            return DirectConnectionResolution(database=None, source_id=None, error=str(error))

        return DirectConnectionResolution(
            database=database,
            source_id=str(source.id) if source else None,
            is_direct_mysql=source.is_direct_mysql if source else False,
        )


def get_hogql_metadata(
    query: HogQLMetadata,
    team: Team,
    user: User | None = None,
    hogql_ast: ast.SelectQuery | ast.SelectSetQuery | None = None,
    prepared_ast: ast.AST | None = None,
    printed_sql: str | None = None,
) -> SchemaHogQLMetadataResponse:
    common_response = get_common_hogql_metadata(
        query=query,
        team=team,
        user=user,
        hogql_ast=hogql_ast,
        prepared_ast=prepared_ast,
        printed_sql=printed_sql,
        metadata_provider=PostHogMetadataProvider(),
    )
    return SchemaHogQLMetadataResponse.model_validate(common_response.model_dump())


def get_common_metadata_for_query_execution(
    query: HogQLMetadataRequest,
    team: Team,
    *,
    user: User | None = None,
    hogql_ast: ast.SelectQuery | ast.SelectSetQuery | None = None,
    prepared_ast: ast.AST | None = None,
    printed_sql: str | None = None,
) -> HogQLMetadataResponse:
    return get_common_hogql_metadata(
        query=query,
        team=team,
        user=user,
        hogql_ast=hogql_ast,
        prepared_ast=prepared_ast,
        printed_sql=printed_sql,
        metadata_provider=PostHogMetadataProvider(),
    )


def enrich_hogql_validation_error(
    query: Any | None,
    team: Team,
    user: User | None,
    original_detail: str,
) -> tuple[str, dict | None]:
    return enrich_common_hogql_validation_error(
        query=query,
        team=team,
        user=user,
        original_detail=original_detail,
        metadata_provider=PostHogMetadataProvider(),
    )
