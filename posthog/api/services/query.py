from typing import TYPE_CHECKING, Optional

import structlog
import pydantic_core
from pydantic import BaseModel
from rest_framework.exceptions import ValidationError

if TYPE_CHECKING:
    from rest_framework.request import Request

from posthog.schema import (
    DashboardFilter,
    DatabaseSchemaField,
    DatabaseSchemaQuery,
    DatabaseSchemaQueryResponse,
    DatabaseSerializedFieldType,
    DataWarehouseViewLink,
    HogQLAutocomplete,
    HogQLMetadata,
    HogQLVariable,
    HogQuery,
    HogQueryResponse,
    QuerySchemaRoot,
)

from posthog.hogql.autocomplete import get_hogql_autocomplete
from posthog.hogql.compiler.bytecode import execute_hog
from posthog.hogql.constants import LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import HOGQL_CHARACTERS_TO_BE_WRAPPED, Database
from posthog.hogql.metadata import get_hogql_metadata
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.source_scoping import (
    connection_source_identifiers,
    filter_schema_tables_for_connection,
    prune_database_for_connection,
)

from posthog.clickhouse.query_tagging import tag_queries
from posthog.cloud_utils import is_cloud
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import CacheMissResponse, ExecutionMode, QueryResponse, get_query_runner
from posthog.models import Team, User
from posthog.schema_migrations.upgrade import upgrade

from products.data_warehouse.backend.models import DataWarehouseJoin, ExternalDataSource
from products.data_warehouse.backend.models.external_data_source import get_external_data_source_for_connection

from common.hogvm.python.debugger import color_bytecode

logger = structlog.get_logger(__name__)


def _validated_source_for_connection(team: Team, connection_id: str | None) -> ExternalDataSource | None:
    source = get_external_data_source_for_connection(team_id=team.pk, connection_id=connection_id)
    if connection_id and source is None:
        raise ValidationError("Invalid connectionId for this team")
    return source


def _database_for_connection_source(team: Team, user: User | None, source: ExternalDataSource | None) -> Database:
    return Database.create_for(
        team=team,
        modifiers=create_default_modifiers_for_team(team),
        user=user,
        direct_query_source_id=str(source.id)
        if source and source.access_method == ExternalDataSource.AccessMethod.DIRECT
        else None,
    )


def _connection_context(
    team: Team,
    connection_id: str | None,
    user: User | None,
    *,
    require_database: bool,
) -> tuple[ExternalDataSource | None, set[str] | None, Database | None]:
    source = _validated_source_for_connection(team, connection_id)
    source_ids = connection_source_identifiers(source)
    database = _database_for_connection_source(team, user, source) if require_database or source else None
    return source, source_ids, database


def _inline_join_field(tables: dict[str, object], join: object) -> None:
    source_table_name = getattr(join, "source_table_name", None)
    joining_table_name = getattr(join, "joining_table_name", None)
    field_name = getattr(join, "field_name", None)
    if not source_table_name or not joining_table_name or not field_name:
        return

    source_table = tables.get(source_table_name)
    joining_table = tables.get(joining_table_name)
    if source_table is None or joining_table is None:
        return

    source_fields = getattr(source_table, "fields", None)
    joining_fields = getattr(joining_table, "fields", None)
    if not isinstance(source_fields, dict) or not isinstance(joining_fields, dict):
        return

    field_type = (
        DatabaseSerializedFieldType.VIEW
        if getattr(joining_table, "type", None) in {"view", "materialized_view", "managed_view"}
        else DatabaseSerializedFieldType.LAZY_TABLE
    )
    hogql_value = (
        f"`{field_name}`"
        if any(character in field_name for character in HOGQL_CHARACTERS_TO_BE_WRAPPED)
        else field_name
    )
    source_fields[field_name] = DatabaseSchemaField(
        name=field_name,
        hogql_value=hogql_value,
        type=field_type,
        schema_valid=True,
        table=getattr(joining_table, "name", joining_table_name),
        fields=None,
        id=str(getattr(joining_table, "id", field_name))
        if field_type == DatabaseSerializedFieldType.VIEW
        else field_name,
    )


def _streamline_join_fields(tables: dict[str, object]) -> None:
    for table in tables.values():
        fields = getattr(table, "fields", None)
        if not isinstance(fields, dict):
            continue

        for field in fields.values():
            if not isinstance(field, DatabaseSchemaField):
                continue
            if field.type in {
                DatabaseSerializedFieldType.LAZY_TABLE,
                DatabaseSerializedFieldType.VIEW,
                DatabaseSerializedFieldType.MATERIALIZED_VIEW,
            }:
                field.fields = None


def process_query_dict(
    team: Team,
    query_json: dict,
    *,
    dashboard_filters_json: Optional[dict] = None,
    variables_override_json: Optional[dict] = None,
    limit_context: Optional[LimitContext] = None,
    execution_mode: ExecutionMode = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
    user: Optional[User] = None,
    query_id: Optional[str] = None,
    insight_id: Optional[int] = None,
    dashboard_id: Optional[int] = None,
    is_query_service: bool = False,
    request: Optional["Request"] = None,
) -> dict | BaseModel:
    upgraded_query_json = upgrade(query_json)
    try:
        model = QuerySchemaRoot.model_validate(upgraded_query_json)
    except pydantic_core.ValidationError as e:
        logger.exception(
            "query_validation_error",
            team_id=team.id,
            dashboard_id=dashboard_id,
            insight_id=insight_id,
            query_id=query_id,
            validation_error=str(e),
        )
        capture_exception(
            e,
            {
                "team_id": team.id,
                "dashboard_id": dashboard_id,
                "insight_id": insight_id,
                "query_id": query_id,
                "error_type": "query_validation_error",
            },
        )

        if dashboard_id:
            raise

        return QueryResponse(results=None, error=str(e))

    tag_queries(query=upgraded_query_json)

    dashboard_filters = DashboardFilter.model_validate(dashboard_filters_json) if dashboard_filters_json else None
    variables_override = (
        [HogQLVariable.model_validate(n) for n in variables_override_json.values()] if variables_override_json else None
    )

    return process_query_model(
        team,
        model.root,
        dashboard_filters=dashboard_filters,
        variables_override=variables_override,
        limit_context=limit_context,
        execution_mode=execution_mode,
        user=user,
        query_id=query_id,
        insight_id=insight_id,
        dashboard_id=dashboard_id,
        is_query_service=is_query_service,
        request=request,
    )


def process_query_model(
    team: Team,
    query: BaseModel,  # mypy has problems with unions and isinstance
    *,
    dashboard_filters: Optional[DashboardFilter] = None,
    variables_override: Optional[list[HogQLVariable]] = None,
    limit_context: Optional[LimitContext] = None,
    execution_mode: ExecutionMode = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
    user: Optional[User] = None,
    query_id: Optional[str] = None,
    insight_id: Optional[int] = None,
    dashboard_id: Optional[int] = None,
    is_query_service: bool = False,
    cache_age_seconds: Optional[int] = None,
    request: Optional["Request"] = None,
) -> dict | BaseModel:
    result: dict | BaseModel

    if isinstance(query, HogQLAutocomplete):
        _, source_ids, database = _connection_context(team, query.connectionId, user, require_database=True)
        assert database is not None
        serialized_tables = database.serialize(HogQLContext(team_id=team.pk, team=team, database=database, user=user))
        filtered_tables = filter_schema_tables_for_connection(serialized_tables, source_ids)
        if set(filtered_tables.keys()) != set(serialized_tables.keys()):
            prune_database_for_connection(database, set(filtered_tables.keys()))
        return get_hogql_autocomplete(query=query, team=team, database_arg=database, user=user)

    if isinstance(query, HogQLMetadata):
        metadata_query = HogQLMetadata.model_validate(query)
        return get_hogql_metadata(query=metadata_query, team=team, user=user)

    if isinstance(query, DatabaseSchemaQuery):
        _, source_ids, database = _connection_context(team, query.connectionId, user, require_database=True)
        assert database is not None
        context = HogQLContext(team_id=team.pk, team=team, database=database, user=user)
        serialized_tables = database.serialize(context, include_hidden_posthog_tables=True)
        filtered_tables = filter_schema_tables_for_connection(serialized_tables, source_ids)
        _streamline_join_fields(filtered_tables)
        table_names = (
            set(filtered_tables.keys()) if source_ids or set(filtered_tables.keys()) != set(serialized_tables) else None
        )
        joins = DataWarehouseJoin.objects.filter(team_id=team.pk).exclude(deleted=True)
        if table_names is not None:
            joins = joins.filter(source_table_name__in=table_names, joining_table_name__in=table_names)

        join_models: list[DataWarehouseViewLink] = []
        for join in joins.iterator():
            _inline_join_field(filtered_tables, join)
            join_models.append(
                DataWarehouseViewLink.model_validate(
                    {
                        "id": str(join.id),
                        "source_table_name": join.source_table_name,
                        "source_table_key": join.source_table_key,
                        "joining_table_name": join.joining_table_name,
                        "joining_table_key": join.joining_table_key,
                        "field_name": join.field_name,
                        "created_at": join.created_at.isoformat(),
                    }
                )
            )

        return DatabaseSchemaQueryResponse(
            tables=filtered_tables,
            joins=join_models,
        )

    try:
        query_runner = get_query_runner(query, team, limit_context=limit_context)
    except ValueError:  # This query doesn't run via query runner
        if hasattr(query, "source") and isinstance(query.source, BaseModel):
            result = process_query_model(
                team,
                query.source,
                dashboard_filters=dashboard_filters,
                variables_override=variables_override,
                limit_context=limit_context,
                execution_mode=execution_mode,
                user=user,
                query_id=query_id,
                insight_id=insight_id,
                dashboard_id=dashboard_id,
                is_query_service=is_query_service,
                cache_age_seconds=cache_age_seconds,
                request=request,
            )
        elif execution_mode == ExecutionMode.CACHE_ONLY_NEVER_CALCULATE:
            # Caching is handled by query runners, so in this case we can only return a cache miss
            result = CacheMissResponse(cache_key=None)
        elif isinstance(query, HogQuery):
            if is_cloud() and (user is None or not user.is_staff):
                return {"results": "Hog queries currently require staff user privileges."}

            try:
                hog_result = execute_hog(query.code or "", team=team)
                bytecode = hog_result.bytecodes.get("root", None)
                result = HogQueryResponse(
                    results=hog_result.result,
                    bytecode=bytecode,
                    coloredBytecode=color_bytecode(bytecode) if bytecode else None,
                    stdout="\n".join(hog_result.stdout),
                )
            except Exception as e:
                result = HogQueryResponse(results=f"ERROR: {str(e)}")
        else:
            raise ValidationError(f"Unsupported query kind: {query.__class__.__name__}")
    else:  # Query runner available - it will handle execution as well as caching
        if dashboard_filters:
            query_runner.apply_dashboard_filters(dashboard_filters)
        if variables_override:
            query_runner.apply_variable_overrides(variables_override)
        query_runner.is_query_service = is_query_service

        result = query_runner.run(
            execution_mode=execution_mode,
            user=user,
            query_id=query_id,
            insight_id=insight_id,
            dashboard_id=dashboard_id,
            cache_age_seconds=cache_age_seconds,
            request=request,
        )

    return result
