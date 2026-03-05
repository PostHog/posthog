from typing import TYPE_CHECKING, Optional
from uuid import UUID

import structlog
import pydantic_core
from pydantic import BaseModel
from rest_framework.exceptions import ValidationError

if TYPE_CHECKING:
    from rest_framework.request import Request

from posthog.schema import (
    DashboardFilter,
    DatabaseSchemaQuery,
    DatabaseSchemaQueryResponse,
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
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import FunctionCallTable, TableNode
from posthog.hogql.metadata import get_hogql_metadata
from posthog.hogql.modifiers import create_default_modifiers_for_team

from posthog.clickhouse.query_tagging import tag_queries
from posthog.cloud_utils import is_cloud
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import CacheMissResponse, ExecutionMode, QueryResponse, get_query_runner
from posthog.models import Team, User
from posthog.schema_migrations.upgrade import upgrade

from products.data_warehouse.backend.models import DataWarehouseJoin, ExternalDataSource

from common.hogvm.python.debugger import color_bytecode

logger = structlog.get_logger(__name__)


def _source_for_connection(team: Team, connection_id: str | None) -> ExternalDataSource | None:
    if not connection_id:
        return None

    sources = ExternalDataSource.objects.filter(team_id=team.pk)

    source = sources.filter(connection_id=connection_id).first()
    if source:
        return source

    source = sources.filter(source_id=connection_id).first()
    if source:
        return source

    try:
        source_uuid = UUID(connection_id)
    except ValueError:
        return None

    return sources.filter(id=source_uuid).first()


def _source_id_for_connection(team: Team, connection_id: str | None) -> str | None:
    source = _source_for_connection(team, connection_id)
    return source.source_id if source else None


def _connection_source_identifiers(source: ExternalDataSource | None) -> set[str] | None:
    if source is None:
        return None

    return {
        identifier
        for identifier in [str(source.id), source.source_id, source.connection_id]
        if identifier is not None and identifier != ""
    }


def _filter_schema_tables_for_connection(tables: dict, source_ids: set[str] | None) -> dict:
    if not source_ids:
        return {
            name: table
            for name, table in tables.items()
            if not (
                getattr(table, "type", None) == "data_warehouse"
                and getattr(getattr(table, "source", None), "access_method", None)
                == ExternalDataSource.AccessMethod.DIRECT
            )
        }

    def _is_queriable(table: object) -> bool:
        schema = getattr(table, "schema_", None) or getattr(table, "schema", None)
        if schema is None:
            return True
        if isinstance(schema, dict):
            return bool(schema.get("should_sync", False))
        return bool(getattr(schema, "should_sync", False))

    return {
        name: table
        for name, table in tables.items()
        if getattr(table, "type", None) == "data_warehouse"
        and str(getattr(getattr(table, "source", None), "id", "")) in source_ids
        and _is_queriable(table)
    }


def _filter_schema_joins_for_connection(
    joins: list[DataWarehouseJoin], table_names: set[str] | None
) -> list[DataWarehouseJoin]:
    if table_names is None:
        return joins

    return [join for join in joins if join.source_table_name in table_names and join.joining_table_name in table_names]


def _prune_database_for_direct_connection(database: Database, allowed_table_names: set[str]) -> None:
    def prune_node(node: TableNode, chain: list[str]) -> bool:
        full_name = ".".join(chain)

        keep_table = node.table is not None and (
            full_name in allowed_table_names or (len(chain) > 0 and isinstance(node.table, FunctionCallTable))
        )

        pruned_children: dict[str, TableNode] = {}
        for child_name, child in node.children.items():
            if prune_node(child, [*chain, child_name]):
                pruned_children[child_name] = child
        node.children = pruned_children

        return node.name == "root" or keep_table or len(node.children) > 0

    prune_node(database.tables, [])
    database._warehouse_table_names = [name for name in database._warehouse_table_names if name in allowed_table_names]
    database._warehouse_self_managed_table_names = [
        name for name in database._warehouse_self_managed_table_names if name in allowed_table_names
    ]
    database._view_table_names = [name for name in database._view_table_names if name in allowed_table_names]


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
        source = _source_for_connection(team, query.connectionId)
        database = None
        if source:
            database = Database.create_for(
                team=team,
                modifiers=create_default_modifiers_for_team(team),
                direct_query_source_id=str(source.id)
                if source and source.access_method == ExternalDataSource.AccessMethod.DIRECT
                else None,
            )
            serialized_tables = database.serialize(
                HogQLContext(team_id=team.pk, team=team, database=database, user=user)
            )
            source_ids = _connection_source_identifiers(source)
            filtered_tables = _filter_schema_tables_for_connection(serialized_tables, source_ids)
            _prune_database_for_direct_connection(database, set(filtered_tables.keys()))
        return get_hogql_autocomplete(query=query, team=team, database_arg=database)

    if isinstance(query, HogQLMetadata):
        metadata_query = HogQLMetadata.model_validate(query)
        return get_hogql_metadata(query=metadata_query, team=team, user=user)

    if isinstance(query, DatabaseSchemaQuery):
        joins = list(DataWarehouseJoin.objects.filter(team_id=team.pk).exclude(deleted=True))
        source = _source_for_connection(team, query.connectionId)
        source_ids = _connection_source_identifiers(source)
        database = Database.create_for(
            team=team,
            modifiers=create_default_modifiers_for_team(team),
            user=user,
            direct_query_source_id=str(source.id)
            if source and source.access_method == ExternalDataSource.AccessMethod.DIRECT
            else None,
        )
        context = HogQLContext(team_id=team.pk, team=team, database=database, user=user)
        filtered_tables = _filter_schema_tables_for_connection(
            database.serialize(context, include_hidden_posthog_tables=True),
            source_ids,
        )
        table_names = set(filtered_tables.keys()) if source_ids else None

        return DatabaseSchemaQueryResponse(
            tables=filtered_tables,
            joins=[
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
                for join in _filter_schema_joins_for_connection(joins, table_names)
            ],
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
