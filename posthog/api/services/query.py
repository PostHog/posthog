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
    result: dict | BaseModel

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
        elif isinstance(query, HogQLAutocomplete):
            result = get_hogql_autocomplete(query=query, team=team)
        elif isinstance(query, HogQLMetadata):
            metadata_query = HogQLMetadata.model_validate(query)
            metadata_response = get_hogql_metadata(query=metadata_query, team=team)
            result = metadata_response
        elif isinstance(query, DatabaseSchemaQuery):
            joins = DataWarehouseJoin.objects.filter(team_id=team.pk).exclude(deleted=True)
            database = create_hogql_database(team=team, modifiers=create_default_modifiers_for_team(team))
            context = HogQLContext(team_id=team.pk, team=team, database=database)
            result = DatabaseSchemaQueryResponse(
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
        )

    return result
