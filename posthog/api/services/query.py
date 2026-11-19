from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional, overload

import structlog
import pydantic_core
from pydantic import BaseModel
from rest_framework.exceptions import APIException, ValidationError

from posthog.schema import (
    DashboardFilter,
    DatabaseSchemaQuery,
    DatabaseSchemaQueryResponse,
    DataWarehouseViewLink,
    HogLanguage,
    HogQLAutocomplete,
    HogQLMetadata,
    HogQLVariable,
    HogQuery,
    HogQueryResponse,
    QuerySchemaRoot,
    QueryStatus,
)

from posthog.hogql.autocomplete import get_hogql_autocomplete
from posthog.hogql.compiler.bytecode import execute_hog
from posthog.hogql.constants import LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.direct_connection import resolve_database_for_connection
from posthog.hogql.editor_assist_metrics import EDITOR_ASSIST_DURATION_SECONDS
from posthog.hogql.errors import ExposedHogQLError, ResolutionError
from posthog.hogql.metadata import get_hogql_metadata
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.timings import HogQLTimings

from posthog.clickhouse.query_tagging import tag_queries
from posthog.cloud_utils import is_cloud
from posthog.dataclasses import frozen
from posthog.event_usage import AnalyticsProps
from posthog.exceptions import DatabaseSchemaUnavailable
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import (
    CacheMissResponse,
    ExecutionMode,
    QueryResponse,
    QueryRunner,
    get_query_runner_or_none,
    unwrapped_source,
)
from posthog.models import Team, User
from posthog.schema_migrations.upgrade import upgrade

from products.access_control.backend.facade.user_access_control import UserAccessControl, UserAccessControlError
from products.data_tools.backend.models.join import DataWarehouseJoin
from products.managed_warehouse.backend.facade.query_execution import get_managed_trino_schema

from common.hogvm.python.debugger import color_bytecode

if TYPE_CHECKING:
    from posthog.hogql.database.database import Database

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
    query_status: QueryStatus | None = ...,
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
    query_status: QueryStatus | None = None,
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
    query_status: QueryStatus | None = None,
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

    dashboard_filters, variables_override = _parse_overrides(dashboard_filters_json, variables_override_json)

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
        query_status=query_status,
        allow_raw_results=allow_raw_results,
    )


def process_database_schema_query(
    team: Team, query: DatabaseSchemaQuery, *, user: Optional[User] = None
) -> DatabaseSchemaQueryResponse:
    if query.executionTarget == "managed_trino":
        try:
            return get_managed_trino_schema(query, team=team, user=user)
        except (APIException, ExposedHogQLError, UserAccessControlError):
            raise
        except Exception as error:
            capture_exception(error, {"team_id": team.pk, "query_kind": "DatabaseSchemaQuery"})
            raise DatabaseSchemaUnavailable() from error
    return _build_database_schema_query(team, query, user=user)


def _build_database_schema_query(
    team: Team, query: DatabaseSchemaQuery, *, user: Optional[User] = None
) -> DatabaseSchemaQueryResponse:
    try:
        _, database = resolve_database_for_connection(
            team,
            query.connectionId,
            user=user,
            error_factory=ValidationError,
            modifiers=create_default_modifiers_for_team(team),
            schema_table_names=set(query.tables) if query.tables else None,
        )
        context = HogQLContext(team_id=team.pk, team=team, database=database, user=user)
        serialized_tables = database.serialize(
            context,
            include_only=set(query.tables) if query.tables else None,
            include_hidden_posthog_tables=True,
            include_fields=query.includeFields is not False,
        )
    except (APIException, ExposedHogQLError, ResolutionError, UserAccessControlError):
        # These already carry an actionable message, and the query view maps them to a 4xx.
        raise
    except Exception as e:
        # This request backs the SQL editor's table list. Untyped, it surfaces as a bare 500 with
        # "A server error occurred.", which the sidebar can't tell apart from an empty project.
        logger.exception(
            "database_schema_query_failed", team_id=team.pk, connection_id=query.connectionId, error=str(e)
        )
        capture_exception(e, {"team_id": team.pk, "query_kind": "DatabaseSchemaQuery"})
        raise DatabaseSchemaUnavailable() from e

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

    return DatabaseSchemaQueryResponse(tables=serialized_tables, joins=join_models)


@frozen
class PlannedQuery:
    """A query's runner, configured with the request's filters and overrides, before it runs.

    Planning first lets a caller compute the cache keys of several queries and read their entries in one round trip.
    """

    query_runner: QueryRunner
    upgraded_query: dict
    cache_key: str


def plan_query_dict(
    team: Team,
    query_json: dict,
    *,
    dashboard_filters_json: Optional[dict],
    variables_override_json: Optional[dict],
    limit_context: Optional[LimitContext],
    user: Optional[User],
    user_access_control: Optional[UserAccessControl],
    allow_raw_results: bool,
) -> Optional[PlannedQuery]:
    """The runner `process_query_dict` would run `query_json` with, configured the same way.

    None when the query doesn't validate or no runner handles it. The caller then goes through `process_query_dict`,
    which reports the error or handles the query as before.
    """
    upgraded_query = upgrade(query_json)
    try:
        query = QuerySchemaRoot.model_validate(upgraded_query).root
    except pydantic_core.ValidationError:
        return None
    query_runner, _ = _find_query_runner(
        query, team, limit_context=limit_context, user=user, user_access_control=user_access_control
    )
    if query_runner is None:
        return None
    dashboard_filters, variables_override = _parse_overrides(dashboard_filters_json, variables_override_json)
    _configure_query_runner(
        query_runner,
        dashboard_filters=dashboard_filters,
        variables_override=variables_override,
        pagination_cursor=None,
        is_query_service=False,
        allow_raw_results=allow_raw_results,
    )
    # run() applies the user before it builds the key. Some runners are built without the user, so apply it here too.
    if user is not None:
        query_runner.set_user(user)
    return PlannedQuery(
        query_runner=query_runner, upgraded_query=upgraded_query, cache_key=query_runner.plan_cache_key()
    )


def _parse_overrides(
    dashboard_filters_json: Optional[dict], variables_override_json: Optional[dict]
) -> tuple[Optional[DashboardFilter], Optional[list[HogQLVariable]]]:
    dashboard_filters = DashboardFilter.model_validate(dashboard_filters_json) if dashboard_filters_json else None
    variables_override = (
        [HogQLVariable.model_validate(n) for n in variables_override_json.values()] if variables_override_json else None
    )
    return dashboard_filters, variables_override


def _find_query_runner(
    query: BaseModel,
    team: Team,
    *,
    limit_context: Optional[LimitContext],
    user: Optional[User],
    user_access_control: Optional[UserAccessControl],
) -> tuple[Optional[QueryRunner], BaseModel]:
    """The runner `process_query_model` runs `query` with: the query's own, or else that of the first source down its
    `source` chain that has one. Also returns the query the search stopped at. The runner is None where
    `process_query_model` handles that query without a runner: editor queries, Hog queries and unsupported kinds.
    """
    if isinstance(query, HogQLAutocomplete | HogQLMetadata | DatabaseSchemaQuery):
        return None, query
    query_runner = get_query_runner_or_none(
        query, team, limit_context=limit_context, user=user, user_access_control=user_access_control
    )
    if query_runner is None and hasattr(query, "source") and isinstance(query.source, BaseModel):
        return _find_query_runner(
            unwrapped_source(query, query.source),
            team,
            limit_context=limit_context,
            user=user,
            user_access_control=user_access_control,
        )
    return query_runner, query


def run_planned_query(
    planned: PlannedQuery,
    *,
    execution_mode: ExecutionMode,
    user: Optional[User],
    insight_id: Optional[int],
    dashboard_id: Optional[int],
    cache_age_seconds: Optional[int],
    analytics_props: Optional[AnalyticsProps],
) -> dict | BaseModel | RawCachedQueryResponse:
    """Run a planned query as `process_query_dict` would have run it."""
    tag_queries(query=planned.upgraded_query)
    query_runner = planned.query_runner
    result = query_runner.run(
        execution_mode=execution_mode,
        user=user,
        insight_id=insight_id,
        dashboard_id=dashboard_id,
        cache_age_seconds=cache_age_seconds,
        analytics_props=analytics_props,
    )
    return _with_raw_results(query_runner, result)


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
    query_status: QueryStatus | None = ...,
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
    query_status: QueryStatus | None = None,
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
    query_status: QueryStatus | None = None,
    allow_raw_results: bool = False,
) -> dict | BaseModel | RawCachedQueryResponse:
    if isinstance(query, HogQLAutocomplete):
        timings = HogQLTimings()
        with EDITOR_ASSIST_DURATION_SECONDS.labels(kind="autocomplete").time():
            with timings.measure("editor_assist"):
                database: Database | None = None
                # Hog and template languages answer from globals, so building the schema is wasted work.
                if query.language in (HogLanguage.HOG_QL, HogLanguage.HOG_QL_EXPR):
                    with timings.measure("database"):
                        _, database = resolve_database_for_connection(
                            team,
                            query.connectionId,
                            user=user,
                            error_factory=ValidationError,
                            modifiers=create_default_modifiers_for_team(team),
                            # Editor-assist only: query execution never reads cached sources.
                            use_cached_sources=True,
                        )
                with timings.measure("autocomplete"):
                    autocomplete_response = get_hogql_autocomplete(
                        query=query, team=team, database_arg=database, user=user
                    )
            autocomplete_response.timings = [
                *(autocomplete_response.timings or []),
                *timings.to_list(back_out_stack=False),
            ]
            return autocomplete_response

    if isinstance(query, HogQLMetadata):
        with EDITOR_ASSIST_DURATION_SECONDS.labels(kind="metadata").time():
            metadata_query = HogQLMetadata.model_validate(query)
            return get_hogql_metadata(query=metadata_query, team=team, user=user)

    if isinstance(query, DatabaseSchemaQuery):
        return process_database_schema_query(team, query, user=user)

    query_runner, runner_query = _find_query_runner(
        query, team, limit_context=limit_context, user=user, user_access_control=user_access_control
    )
    if query_runner is not None:  # Query runner available - it will handle execution as well as caching
        return _run_query_runner(
            query_runner,
            dashboard_filters=dashboard_filters,
            variables_override=variables_override,
            execution_mode=execution_mode,
            user=user,
            query_id=query_id,
            insight_id=insight_id,
            dashboard_id=dashboard_id,
            is_query_service=is_query_service,
            cache_age_seconds=cache_age_seconds,
            # The cursor applies to the query as sent, so a runner found down its source chain runs without it.
            pagination_cursor=pagination_cursor if runner_query is query else None,
            analytics_props=analytics_props,
            query_status=query_status,
            allow_raw_results=allow_raw_results,
        )

    # This query doesn't run via query runner
    if runner_query is not query:
        return process_query_model(
            team,
            runner_query,
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
            query_status=query_status,
            allow_raw_results=allow_raw_results,
        )
    if execution_mode == ExecutionMode.CACHE_ONLY_NEVER_CALCULATE:
        # Caching is handled by query runners, so in this case we can only return a cache miss
        return CacheMissResponse(cache_key=None)
    if isinstance(query, HogQuery):
        return _run_hog_query(query, team, user)
    raise ValidationError(f"Unsupported query kind: {query.__class__.__name__}")


def _run_hog_query(query: HogQuery, team: Team, user: Optional[User]) -> dict | HogQueryResponse:
    if is_cloud() and (user is None or not user.is_staff):
        return {"results": "Hog queries currently require staff user privileges."}

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


def _run_query_runner(
    query_runner: QueryRunner,
    *,
    dashboard_filters: Optional[DashboardFilter],
    variables_override: Optional[list[HogQLVariable]],
    execution_mode: ExecutionMode,
    user: Optional[User],
    query_id: Optional[str],
    insight_id: Optional[int],
    dashboard_id: Optional[int],
    is_query_service: bool,
    cache_age_seconds: Optional[int],
    pagination_cursor: Optional[str],
    analytics_props: Optional[AnalyticsProps],
    query_status: QueryStatus | None = None,
    allow_raw_results: bool,
) -> dict | BaseModel | RawCachedQueryResponse:
    _configure_query_runner(
        query_runner,
        dashboard_filters=dashboard_filters,
        variables_override=variables_override,
        pagination_cursor=pagination_cursor,
        is_query_service=is_query_service,
        allow_raw_results=allow_raw_results,
    )

    # The worker rebuilds the runner, so enqueue-time labels can describe a different access snapshot.
    labels = query_runner.query_status_labels() if query_status is not None else None
    result = query_runner.run(
        execution_mode=execution_mode,
        user=user,
        query_id=query_id,
        insight_id=insight_id,
        dashboard_id=dashboard_id,
        cache_age_seconds=cache_age_seconds,
        analytics_props=analytics_props,
    )
    if query_status is not None and labels is not None:
        query_status.labels = [*labels, *(["chained"] if "chained" in (query_status.labels or []) else [])]
    return _with_raw_results(query_runner, result)


def _configure_query_runner(
    query_runner: QueryRunner,
    *,
    dashboard_filters: Optional[DashboardFilter],
    variables_override: Optional[list[HogQLVariable]],
    pagination_cursor: Optional[str],
    is_query_service: bool,
    allow_raw_results: bool,
) -> None:
    """Everything that shapes a runner's query and cache key before it runs. Planning a query configures it here too,
    so a planned key is the key the run reads."""
    if dashboard_filters:
        query_runner.apply_dashboard_filters(dashboard_filters)
        # A tag, so it reaches the async worker, which rebuilds the runner from the query alone.
        tag_queries(dashboard_all_time=dashboard_filters.date_from == "all")
    if variables_override:
        query_runner.apply_variable_overrides(variables_override)
    if pagination_cursor:
        query_runner.apply_pagination_cursor(pagination_cursor)
    query_runner.is_query_service = is_query_service
    if allow_raw_results:
        query_runner.serve_raw_cached_results = True


def _with_raw_results(query_runner: QueryRunner, result: dict | BaseModel) -> dict | BaseModel | RawCachedQueryResponse:
    raw_results = query_runner.raw_cached_results_bytes
    if raw_results is not None and isinstance(result, BaseModel):
        return RawCachedQueryResponse(response=result, raw_results=raw_results)
    return result
