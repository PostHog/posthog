from dataclasses import dataclass
from typing import Literal, Optional, overload

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
from posthog.hogql.direct_connection import resolve_database_for_connection
from posthog.hogql.metadata import get_hogql_metadata
from posthog.hogql.modifiers import create_default_modifiers_for_team

from posthog.clickhouse.query_tagging import tag_queries
from posthog.cloud_utils import is_cloud
from posthog.event_usage import AnalyticsProps
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import CacheMissResponse, ExecutionMode, QueryResponse, get_query_runner_or_none
from posthog.models import Team, User
from posthog.rbac.user_access_control import UserAccessControl
from posthog.schema_migrations.upgrade import upgrade

from products.data_tools.backend.models.join import DataWarehouseJoin

from common.hogvm.python.debugger import color_bytecode

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RawCachedQueryResponse:
    """A cached query response whose `results` field is carried as raw JSON bytes.

    `response.results` holds an empty-list placeholder; `raw_results` is the JSON-encoded
    results segment straight from the cache, ready to be embedded into a JSON response
    (e.g. via orjson.Fragment) without a parse/re-serialize round trip. Only produced when
    a caller passes allow_raw_results=True.
    """

    response: BaseModel
    raw_results: bytes


# The overloads keep the public contract at `dict | BaseModel` for the vast majority of
# callers: only allow_raw_results=True can produce a RawCachedQueryResponse.
@overload
def process_query_dict(
    team: Team,
    query_json: dict,
    *,
    dashboard_filters_json: Optional[dict] = ...,
    variables_override_json: Optional[dict] = ...,
    limit_context: Optional[LimitContext] = ...,
    execution_mode: ExecutionMode = ...,
    user: Optional[User] = ...,
    user_access_control: Optional[UserAccessControl] = ...,
    query_id: Optional[str] = ...,
    insight_id: Optional[int] = ...,
    dashboard_id: Optional[int] = ...,
    is_query_service: bool = ...,
    cache_age_seconds: Optional[int] = ...,
    pagination_cursor: Optional[str] = ...,
    analytics_props: Optional[AnalyticsProps] = ...,
    allow_raw_results: Literal[False] = ...,
) -> dict | BaseModel: ...


@overload
def process_query_dict(
    team: Team,
    query_json: dict,
    *,
    dashboard_filters_json: Optional[dict] = ...,
    variables_override_json: Optional[dict] = ...,
    limit_context: Optional[LimitContext] = ...,
    execution_mode: ExecutionMode = ...,
    user: Optional[User] = ...,
    user_access_control: Optional[UserAccessControl] = ...,
    query_id: Optional[str] = ...,
    insight_id: Optional[int] = ...,
    dashboard_id: Optional[int] = ...,
    is_query_service: bool = ...,
    cache_age_seconds: Optional[int] = ...,
    pagination_cursor: Optional[str] = ...,
    analytics_props: Optional[AnalyticsProps] = ...,
    allow_raw_results: bool,
) -> dict | BaseModel | RawCachedQueryResponse: ...


def process_query_dict(
    team: Team,
    query_json: dict,
    *,
    dashboard_filters_json: Optional[dict] = None,
    variables_override_json: Optional[dict] = None,
    limit_context: Optional[LimitContext] = None,
    execution_mode: ExecutionMode = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
    user: Optional[User] = None,
    user_access_control: Optional[UserAccessControl] = None,
    query_id: Optional[str] = None,
    insight_id: Optional[int] = None,
    dashboard_id: Optional[int] = None,
    is_query_service: bool = False,
    cache_age_seconds: Optional[int] = None,
    pagination_cursor: Optional[str] = None,
    analytics_props: Optional[AnalyticsProps] = None,
    allow_raw_results: bool = False,
) -> dict | BaseModel | RawCachedQueryResponse:
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
        user_access_control=user_access_control,
        query_id=query_id,
        insight_id=insight_id,
        dashboard_id=dashboard_id,
        is_query_service=is_query_service,
        cache_age_seconds=cache_age_seconds,
        pagination_cursor=pagination_cursor,
        analytics_props=analytics_props,
        allow_raw_results=allow_raw_results,
    )


@overload
def process_query_model(
    team: Team,
    query: BaseModel,
    *,
    dashboard_filters: Optional[DashboardFilter] = ...,
    variables_override: Optional[list[HogQLVariable]] = ...,
    limit_context: Optional[LimitContext] = ...,
    execution_mode: ExecutionMode = ...,
    user: Optional[User] = ...,
    user_access_control: Optional[UserAccessControl] = ...,
    query_id: Optional[str] = ...,
    insight_id: Optional[int] = ...,
    dashboard_id: Optional[int] = ...,
    is_query_service: bool = ...,
    cache_age_seconds: Optional[int] = ...,
    pagination_cursor: Optional[str] = ...,
    analytics_props: Optional[AnalyticsProps] = ...,
    allow_raw_results: Literal[False] = ...,
) -> dict | BaseModel: ...


@overload
def process_query_model(
    team: Team,
    query: BaseModel,
    *,
    dashboard_filters: Optional[DashboardFilter] = ...,
    variables_override: Optional[list[HogQLVariable]] = ...,
    limit_context: Optional[LimitContext] = ...,
    execution_mode: ExecutionMode = ...,
    user: Optional[User] = ...,
    user_access_control: Optional[UserAccessControl] = ...,
    query_id: Optional[str] = ...,
    insight_id: Optional[int] = ...,
    dashboard_id: Optional[int] = ...,
    is_query_service: bool = ...,
    cache_age_seconds: Optional[int] = ...,
    pagination_cursor: Optional[str] = ...,
    analytics_props: Optional[AnalyticsProps] = ...,
    allow_raw_results: bool,
) -> dict | BaseModel | RawCachedQueryResponse: ...


def process_query_model(
    team: Team,
    query: BaseModel,  # mypy has problems with unions and isinstance
    *,
    dashboard_filters: Optional[DashboardFilter] = None,
    variables_override: Optional[list[HogQLVariable]] = None,
    limit_context: Optional[LimitContext] = None,
    execution_mode: ExecutionMode = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
    user: Optional[User] = None,
    user_access_control: Optional[UserAccessControl] = None,
    query_id: Optional[str] = None,
    insight_id: Optional[int] = None,
    dashboard_id: Optional[int] = None,
    is_query_service: bool = False,
    cache_age_seconds: Optional[int] = None,
    pagination_cursor: Optional[str] = None,
    analytics_props: Optional[AnalyticsProps] = None,
    allow_raw_results: bool = False,
) -> dict | BaseModel | RawCachedQueryResponse:
    result: dict | BaseModel | RawCachedQueryResponse

    if isinstance(query, HogQLAutocomplete):
        _, database = resolve_database_for_connection(
            team,
            query.connectionId,
            user=user,
            error_factory=ValidationError,
            modifiers=create_default_modifiers_for_team(team),
        )
        return get_hogql_autocomplete(query=query, team=team, database_arg=database, user=user)

    if isinstance(query, HogQLMetadata):
        metadata_query = HogQLMetadata.model_validate(query)
        return get_hogql_metadata(query=metadata_query, team=team, user=user)

    if isinstance(query, DatabaseSchemaQuery):
        _, database = resolve_database_for_connection(
            team,
            query.connectionId,
            user=user,
            error_factory=ValidationError,
            modifiers=create_default_modifiers_for_team(team),
        )
        context = HogQLContext(team_id=team.pk, team=team, database=database, user=user)
        serialized_tables = database.serialize(context, include_hidden_posthog_tables=True)
        table_names = set(serialized_tables.keys())
        joins = DataWarehouseJoin.objects.filter(team_id=team.pk).exclude(deleted=True)
        joins = joins.filter(source_table_name__in=table_names, joining_table_name__in=table_names)

        join_models: list[DataWarehouseViewLink] = []
        for join in joins.iterator():
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
            tables=serialized_tables,
            joins=join_models,
        )

    query_runner = get_query_runner_or_none(
        query, team, limit_context=limit_context, user=user, user_access_control=user_access_control
    )
    if query_runner is None:  # This query doesn't run via query runner
        if hasattr(query, "source") and isinstance(query.source, BaseModel):
            result = process_query_model(
                team,
                query.source,
                dashboard_filters=dashboard_filters,
                variables_override=variables_override,
                limit_context=limit_context,
                execution_mode=execution_mode,
                user=user,
                user_access_control=user_access_control,
                query_id=query_id,
                insight_id=insight_id,
                dashboard_id=dashboard_id,
                is_query_service=is_query_service,
                cache_age_seconds=cache_age_seconds,
                analytics_props=analytics_props,
                allow_raw_results=allow_raw_results,
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
        if pagination_cursor:
            query_runner.apply_pagination_cursor(pagination_cursor)
        query_runner.is_query_service = is_query_service
        if allow_raw_results:
            query_runner.serve_raw_cached_results = True

        result = query_runner.run(
            execution_mode=execution_mode,
            user=user,
            query_id=query_id,
            insight_id=insight_id,
            dashboard_id=dashboard_id,
            cache_age_seconds=cache_age_seconds,
            analytics_props=analytics_props,
        )
        raw_results = query_runner.raw_cached_results_bytes
        if raw_results is not None and isinstance(result, BaseModel):
            return RawCachedQueryResponse(response=result, raw_results=raw_results)

    return result
