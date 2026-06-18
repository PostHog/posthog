from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from common.hogql import ast
    from common.hogql.context import HogQLContext
    from common.hogql.models import HogQLMetadataRequest, HogQLMetadataResponse


@dataclass(frozen=True, slots=True)
class AutocompletePropertyDefinition:
    name: str
    property_type: str | None


@dataclass(frozen=True, slots=True)
class DirectConnectionResolution:
    database: Any | None
    source_id: str | None
    is_direct_mysql: bool = False
    error: str | None = None


class HogQLAutocompleteProvider(Protocol):
    def capture_exception(self, exception: Exception) -> None: ...

    def source_query_to_select(self, source_query: Any, team: Any) -> ast.SelectQuery: ...

    def list_property_definitions(
        self,
        *,
        team: Any,
        property_type: int,
        match: str,
        limit: int,
    ) -> tuple[list[AutocompletePropertyDefinition], bool]: ...

    def list_insight_variable_code_names(self, *, team: Any) -> list[str]: ...


@dataclass(frozen=True, slots=True)
class InsightVariableDefinition:
    code_name: str
    default_value: Any


class HogQLVariableProvider(Protocol):
    def list_insight_variables(self, *, team: Any, variable_ids: list[Any]) -> list[InsightVariableDefinition]: ...


class HogQLSourceQueryProvider(Protocol):
    def source_query_to_select(self, source_query: Any, team: Any) -> ast.SelectQuery | ast.SelectSetQuery: ...


class HogQLMetadataProvider(HogQLSourceQueryProvider, HogQLVariableProvider, Protocol):
    @property
    def debug_errors(self) -> bool: ...

    def resolve_database_for_connection(
        self,
        *,
        team: Any,
        connection_id: str | None,
        user: Any | None,
        modifiers: Any,
    ) -> DirectConnectionResolution: ...


class HogQLQueryProvider(HogQLSourceQueryProvider, HogQLVariableProvider, Protocol):
    increased_max_execution_time: int
    exposed_clickhouse_query_error: type[Exception]

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
    ) -> None: ...

    def sync_execute(
        self,
        query: str,
        values: dict[str, Any],
        *,
        with_column_types: bool,
        workload: Any,
        team_id: int,
        readonly: bool,
    ) -> Any: ...

    def sync_explain(
        self,
        query: str,
        values: dict[str, Any],
        *,
        with_column_types: bool,
        workload: Any,
        team_id: int,
        readonly: bool,
    ) -> Any: ...

    def capture_exception(
        self,
        exception: Exception,
        additional_properties: dict[str, Any] | None = None,
    ) -> None: ...

    def create_preaggregated_intermediate_results_transformer(self, context: HogQLContext) -> Any: ...

    def get_hogql_metadata(
        self,
        query: HogQLMetadataRequest,
        team: Any,
        *,
        user: Any | None = None,
        hogql_ast: ast.SelectQuery | ast.SelectSetQuery | None = None,
        prepared_ast: ast.AST | None = None,
        printed_sql: str | None = None,
    ) -> HogQLMetadataResponse: ...

    def get_postgres_sslmode(self, require_ssl: bool) -> str: ...

    def source_requires_ssl(self, source: Any, source_config: Any) -> bool: ...
