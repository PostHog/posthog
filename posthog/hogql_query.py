from typing import Any

from common.hogql import ast
from common.hogql.context import HogQLContext
from common.hogql.dependencies import HogQLQueryProvider
from common.hogql.models import HogQLMetadataRequest, HogQLMetadataResponse

from posthog import settings
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import tag_queries
from posthog.errors import ExposedCHQueryError
from posthog.exceptions_capture import capture_exception
from posthog.hogql_metadata import get_common_metadata_for_query_execution
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.hogql_variables import PostHogVariableProvider
from posthog.models.team import Team
from posthog.models.user import User
from posthog.temporal.data_imports.sources.postgres.postgres import _get_sslmode, source_requires_ssl


class PostHogQueryProvider(PostHogVariableProvider, HogQLQueryProvider):
    increased_max_execution_time = settings.HOGQL_INCREASED_MAX_EXECUTION_TIME
    exposed_clickhouse_query_error = ExposedCHQueryError

    def source_query_to_select(self, source_query: Any, team: Team) -> ast.SelectQuery | ast.SelectSetQuery:
        return get_query_runner(query=source_query, team=team).to_query()

    def tag_queries(
        self,
        *,
        team_id: int,
        query_type: str,
        has_joins: bool,
        has_json_operations: bool,
        hogql_features: Any,
        timings: dict[str, float],
        modifiers: dict[str, Any],
    ) -> None:
        tag_queries(
            team_id=team_id,
            query_type=query_type,
            has_joins=has_joins,
            has_json_operations=has_json_operations,
            hogql_features=hogql_features,
            timings=timings,
            modifiers=modifiers,
        )

    def sync_execute(
        self,
        query: str,
        values: dict[str, Any],
        *,
        with_column_types: bool,
        workload: Any,
        team_id: int,
        readonly: bool,
    ) -> Any:
        return sync_execute(
            query,
            values,
            with_column_types=with_column_types,
            workload=workload,
            team_id=team_id,
            readonly=readonly,
        )

    def sync_explain(
        self,
        query: str,
        values: dict[str, Any],
        *,
        with_column_types: bool,
        workload: Any,
        team_id: int,
        readonly: bool,
    ) -> Any:
        return sync_execute(
            f"EXPLAIN {query}",
            values,
            with_column_types=with_column_types,
            workload=workload,
            team_id=team_id,
            readonly=readonly,
        )

    def capture_exception(
        self,
        exception: Exception,
        additional_properties: dict[str, Any] | None = None,
    ) -> None:
        capture_exception(exception, additional_properties=additional_properties)

    def create_preaggregated_intermediate_results_transformer(self, context: HogQLContext) -> Any:
        from products.analytics_platform.backend.lazy_computation.lazy_computation_transformer import (  # noqa: PLC0415 - only used when this optimizer is enabled
            Transformer,
        )

        return Transformer(context)

    def get_hogql_metadata(
        self,
        query: HogQLMetadataRequest,
        team: Team,
        *,
        user: User | None = None,
        hogql_ast: ast.SelectQuery | ast.SelectSetQuery | None = None,
        prepared_ast: ast.AST | None = None,
        printed_sql: str | None = None,
    ) -> HogQLMetadataResponse:
        return get_common_metadata_for_query_execution(
            query=query,
            team=team,
            user=user,
            hogql_ast=hogql_ast,
            prepared_ast=prepared_ast,
            printed_sql=printed_sql,
        )

    def get_postgres_sslmode(self, require_ssl: bool) -> str:
        return _get_sslmode(require_ssl)

    def source_requires_ssl(self, source: Any, source_config: Any) -> bool:
        return source_requires_ssl(source, source_config)
