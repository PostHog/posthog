from typing import Optional

import structlog
import pydantic_core
from pydantic import BaseModel
from rest_framework.exceptions import ValidationError

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
from posthog.hogql.database.database import create_hogql_database, serialize_database
from posthog.hogql.metadata import get_hogql_metadata
from posthog.hogql.modifiers import create_default_modifiers_for_team

from posthog.clickhouse.query_tagging import tag_queries
from posthog.cloud_utils import is_cloud
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import CacheMissResponse, ExecutionMode, QueryResponse, get_query_runner
from posthog.models import Team, User
from posthog.schema_migrations.upgrade import upgrade
from posthog.warehouse.models import DataWarehouseJoin

from common.hogvm.python.debugger import color_bytecode

logger = structlog.get_logger(__name__)


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
    )


def _handle_recursive_query(query: BaseModel, team: Team, **kwargs) -> dict | BaseModel:
    """Handle queries with nested source attributes."""
    return process_query_model(team, query.source, **kwargs)


def _handle_hog_query(query: HogQuery, team: Team, user: Optional[User] = None) -> HogQueryResponse:
    """Handle HogQuery execution."""
    if is_cloud() and (user is None or not user.is_staff):
        return HogQueryResponse(results="Hog queries currently require staff user privileges.")

    try:
        hog_result = execute_hog(query.code or "", team=team)
        bytecode = hog_result.bytecodes.get("root", None)
        return HogQueryResponse(
            results=hog_result.result,
            bytecode=bytecode,
            coloredBytecode=color_bytecode(bytecode) if bytecode else None,
            stdout="\n".join(hog_result.stdout),
        )
    except Exception as e:
        return HogQueryResponse(results=f"ERROR: {str(e)}")


def _handle_database_schema_query(query: DatabaseSchemaQuery, team: Team) -> DatabaseSchemaQueryResponse:
    """Handle DatabaseSchemaQuery execution."""
    joins = DataWarehouseJoin.objects.filter(team_id=team.pk).exclude(deleted=True)
    database = create_hogql_database(team=team, modifiers=create_default_modifiers_for_team(team))
    context = HogQLContext(team_id=team.pk, team=team, database=database)
    return DatabaseSchemaQueryResponse(
        tables=serialize_database(context),
        joins=[
            DataWarehouseViewLink.model_validate(
                {
                    "id": str(join.id),
                    "source_table_name": join.source_table_name,
                    "source_table_key": join.source_table_key,
                    "joining_table_name": join.joining_table_name,
                    "joining_table_key": join.joining_table_key,
                    "field_name": join.field_name,
                    "configuration": join.configuration,
                    "created_at": join.created_at.isoformat(),
                }
            )
            for join in joins
        ],
    )


def _handle_non_runner_query(
    query: BaseModel,
    team: Team,
    execution_mode: ExecutionMode,
    user: Optional[User] = None,
    **kwargs,
) -> dict | BaseModel:
    """Handle queries that don't use QueryRunner pattern."""
    if hasattr(query, "source") and isinstance(query.source, BaseModel):
        return _handle_recursive_query(query, team, execution_mode=execution_mode, user=user, **kwargs)
    elif execution_mode == ExecutionMode.CACHE_ONLY_NEVER_CALCULATE:
        # Caching is handled by query runners, so in this case we can only return a cache miss
        return CacheMissResponse(cache_key=None)
    elif isinstance(query, HogQuery):
        return _handle_hog_query(query, team, user)
    elif isinstance(query, HogQLAutocomplete):
        return get_hogql_autocomplete(query=query, team=team)
    elif isinstance(query, HogQLMetadata):
        metadata_query = HogQLMetadata.model_validate(query)
        return get_hogql_metadata(query=metadata_query, team=team)
    elif isinstance(query, DatabaseSchemaQuery):
        return _handle_database_schema_query(query, team)
    else:
        raise ValidationError(f"Unsupported query kind: {query.__class__.__name__}")


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
) -> dict | BaseModel:
    try:
        query_runner = get_query_runner(query, team, limit_context=limit_context)
    except ValueError:  # This query doesn't run via query runner
        return _handle_non_runner_query(
            query=query,
            team=team,
            dashboard_filters=dashboard_filters,
            variables_override=variables_override,
            limit_context=limit_context,
            execution_mode=execution_mode,
            user=user,
            query_id=query_id,
            insight_id=insight_id,
            dashboard_id=dashboard_id,
            is_query_service=is_query_service,
        )
    else:  # Query runner available - it will handle execution as well as caching
        if dashboard_filters:
            query_runner.apply_dashboard_filters(dashboard_filters)
        if variables_override:
            query_runner.apply_variable_overrides(variables_override)
        query_runner.is_query_service = is_query_service
        return query_runner.run(
            execution_mode=execution_mode,
            user=user,
            query_id=query_id,
            insight_id=insight_id,
            dashboard_id=dashboard_id,
        )
