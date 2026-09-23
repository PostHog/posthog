from __future__ import annotations

import time
from contextlib import nullcontext
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional, overload

import structlog
import pydantic_core
import posthoganalytics
from pydantic import BaseModel
from rest_framework.exceptions import APIException, ValidationError

from posthog.schema import (
    DashboardFilter,
    DatabaseSchemaQuery,
    DatabaseSchemaQueryResponse,
    DataWarehouseViewLink,
    HogLanguage,
    HogQLAutocomplete,
    HogQLAutocompleteResponse,
    HogQLMetadata,
    HogQLMetadataResponse,
    HogQLNotice,
    HogQLQuery,
    HogQLVariable,
    HogQuery,
    HogQueryResponse,
    QuerySchemaRoot,
    QueryTiming,
)

from posthog.hogql.autocomplete import get_hogql_autocomplete
from posthog.hogql.compiler.bytecode import execute_hog
from posthog.hogql.constants import LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.direct_connection import resolve_database_for_connection
from posthog.hogql.editor_assist_metrics import EDITOR_ASSIST_DURATION_SECONDS, EDITOR_ASSIST_RESPONSES_TOTAL
from posthog.hogql.errors import ExposedHogQLError, ResolutionError
from posthog.hogql.language_service import (
    WAREHOUSE_ALIAS_CATALOG_REVISION_PREFIX,
    CatalogMissing,
    LanguageServiceClient,
    LanguageServiceError,
    LanguageServiceResult,
    MalformedLanguageServiceResponse,
    build_catalog,
    coordinate_catalog_publication,
    is_language_service_enabled,
)
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
)
from posthog.models import Team, User
from posthog.schema_migrations.upgrade import upgrade

from products.access_control.backend.facade.user_access_control import UserAccessControl, UserAccessControlError
from products.data_tools.backend.models.join import DataWarehouseJoin

from common.hogvm.python.debugger import color_bytecode

if TYPE_CHECKING:
    from posthog.hogql.database.database import Database

logger = structlog.get_logger(__name__)


@frozen
class _DatabaseSchemaCatalog:
    response: DatabaseSchemaQueryResponse
    database: Database


type _EditorAssistReason = Literal["served", "ineligible", "service_error", "invalid_response"]
type _EditorAssistOperation = Literal["autocomplete", "metadata"]
type _MalformedResponseStage = Literal["http_response", "response_mapping"]


@frozen
class _EditorAssistRoute:
    enabled: bool
    result: LanguageServiceResult | None
    reason: _EditorAssistReason
    malformed_stage: _MalformedResponseStage | None = None


def _is_alias_capable_catalog_revision(revision: object) -> bool:
    return isinstance(revision, str) and revision.startswith(WAREHOUSE_ALIAS_CATALOG_REVISION_PREFIX)


def _language_service_eligible(query: HogQLAutocomplete | HogQLMetadata) -> bool:
    common = (
        query.language.value == "hogQL"
        and query.connectionId is None
        and query.globals is None
        and query.filters is None
        and query.modifiers is None
    )
    if isinstance(query, HogQLMetadata):
        return (
            common
            and (query.sourceQuery is None or isinstance(query.sourceQuery, HogQLQuery))
            and query.variables is None
            and not query.debug
        )
    return common and (query.sourceQuery is None or isinstance(query.sourceQuery, HogQLQuery))


def _language_service_call(
    team: Team,
    user: User,
    query: HogQLAutocomplete | HogQLMetadata,
    timings: HogQLTimings | None = None,
) -> _EditorAssistRoute:
    try:
        client = LanguageServiceClient()

        def call() -> LanguageServiceResult:
            if isinstance(query, HogQLAutocomplete):
                return client.autocomplete(team.pk, user.pk, query.query, query.endPosition)
            return client.validate(team.pk, user.pk, query.query)

        with timings.measure("language_service_initial") if timings is not None else nullcontext():
            result = call()
    except CatalogMissing:
        result = None
    except MalformedLanguageServiceResponse:
        return _EditorAssistRoute(enabled=True, result=None, reason="invalid_response", malformed_stage="http_response")
    except LanguageServiceError:
        return _EditorAssistRoute(enabled=True, result=None, reason="service_error")

    if result is not None:
        if _is_alias_capable_catalog_revision(result.body.get("catalogRevision")):
            return _EditorAssistRoute(enabled=True, result=result, reason="served")

    publication_succeeded = False

    def publish_catalog() -> None:
        nonlocal publication_succeeded
        with timings.measure("catalog_schema") if timings is not None else nullcontext():
            schema_catalog = _build_database_schema_query(team, DatabaseSchemaQuery(), user=user)
        revision = f"{WAREHOUSE_ALIAS_CATALOG_REVISION_PREFIX}{time.time_ns()}"
        with timings.measure("catalog_build") if timings is not None else nullcontext():
            catalog = build_catalog(
                team,
                user,
                schema_catalog.response,
                database=schema_catalog.database,
            )
        with timings.measure("catalog_publish") if timings is not None else nullcontext():
            client.publish(team.pk, user.pk, revision, catalog)
        publication_succeeded = True

    def check_catalog() -> LanguageServiceResult | None:
        try:
            current = call()
        except CatalogMissing:
            return None
        if not _is_alias_capable_catalog_revision(current.body.get("catalogRevision")):
            if publication_succeeded:
                raise MalformedLanguageServiceResponse("language service returned an incompatible catalog revision")
            return None
        return current

    try:
        with timings.measure("catalog_coordination") if timings is not None else nullcontext():
            result = coordinate_catalog_publication(
                team.pk,
                user.pk,
                client.base_url,
                check_catalog,
                publish_catalog,
                timings=timings,
            )
    except MalformedLanguageServiceResponse:
        return _EditorAssistRoute(enabled=True, result=None, reason="invalid_response", malformed_stage="http_response")
    except (DatabaseSchemaUnavailable, LanguageServiceError):
        return _EditorAssistRoute(enabled=True, result=None, reason="service_error")
    if result is None:
        return _EditorAssistRoute(enabled=True, result=None, reason="service_error")
    return _EditorAssistRoute(enabled=True, result=result, reason="served")


def _route_editor_assist(
    team: Team,
    user: User | None,
    query: HogQLAutocomplete | HogQLMetadata,
    timings: HogQLTimings | None = None,
) -> _EditorAssistRoute:
    with timings.measure("routing") if timings is not None else nullcontext():
        if user is None or not is_language_service_enabled(team, user):
            return _EditorAssistRoute(enabled=False, result=None, reason="ineligible")
        if not _language_service_eligible(query):
            return _EditorAssistRoute(enabled=True, result=None, reason="ineligible")
    return _language_service_call(team, user, query, timings=timings)


def _capture_malformed_language_service_response(
    operation: _EditorAssistOperation, stage: _MalformedResponseStage
) -> None:
    try:
        with posthoganalytics.new_context(fresh=True, capture_exceptions=False):
            posthoganalytics.set_capture_exception_code_variables_context(False)
            posthoganalytics.capture_exception(
                RuntimeError("HogQL language service returned a malformed response"),
                properties={
                    "component": "hogql_language_service",
                    "operation": operation,
                    "stage": stage,
                },
            )
    except Exception:
        logger.warning("hogql_language_service_error_tracking_failed")


def _record_editor_assist_backend(
    route: _EditorAssistRoute,
    operation: _EditorAssistOperation,
    backend: Literal["language_service", "python"],
    reason: _EditorAssistReason,
) -> None:
    if not route.enabled:
        return
    try:
        EDITOR_ASSIST_RESPONSES_TOTAL.labels(operation=operation, backend=backend, reason=reason).inc()
    except Exception:
        logger.warning("hogql_editor_assist_metric_failed")


def _autocomplete_response_from_language_service(
    language_result: LanguageServiceResult,
) -> HogQLAutocompleteResponse:
    body = language_result.body
    if not isinstance(body.get("suggestions"), list):
        raise TypeError("suggestions must be a list")
    kind_map = {
        "field": "Field",
        "function": "Function",
        "keyword": "Keyword",
        "operator": "Operator",
        "property": "Property",
        "table": "Class",
    }
    return HogQLAutocompleteResponse(
        suggestions=[
            {
                "label": suggestion["label"],
                "insertText": suggestion.get("insertText", suggestion["label"]),
                "kind": kind_map.get(suggestion["kind"], "Text"),
                "detail": suggestion.get("detail"),
                "sortText": suggestion.get("sortText"),
            }
            for suggestion in body["suggestions"]
        ],
        incomplete_list=bool(body.get("nextCursor")),
        timings=[
            QueryTiming(k="language_service_http", t=language_result.duration_seconds),
            QueryTiming(k="language_service_go", t=body["durationMicros"] / 1_000_000),
        ],
    )


def _metadata_response_from_language_service(
    query: HogQLMetadata, language_result: LanguageServiceResult
) -> HogQLMetadataResponse:
    body = language_result.body
    if not isinstance(body.get("diagnostics"), list):
        raise TypeError("diagnostics must be a list")
    errors: list[HogQLNotice] = []
    warnings: list[HogQLNotice] = []
    for diagnostic in body["diagnostics"]:
        notice = HogQLNotice(
            message=diagnostic["message"],
            start=diagnostic["start"],
            end=diagnostic["end"],
            fix=diagnostic["suggestions"][0]["label"] if diagnostic.get("suggestions") else None,
        )
        if diagnostic["code"] == "unknown_property":
            warnings.append(notice)
        else:
            errors.append(notice)
    return HogQLMetadataResponse(
        isValid=not errors,
        query=query.query,
        errors=errors,
        warnings=warnings,
        notices=[],
        table_names=body.get("tableNames", []),
    )


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


def process_database_schema_query(
    team: Team, query: DatabaseSchemaQuery, *, user: Optional[User] = None
) -> DatabaseSchemaQueryResponse:
    return _build_database_schema_query(team, query, user=user).response


def _build_database_schema_query(
    team: Team, query: DatabaseSchemaQuery, *, user: Optional[User] = None
) -> _DatabaseSchemaCatalog:
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

    return _DatabaseSchemaCatalog(
        response=DatabaseSchemaQueryResponse(tables=serialized_tables, joins=join_models), database=database
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
    if isinstance(query, HogQLAutocomplete):
        timings = HogQLTimings()
        with EDITOR_ASSIST_DURATION_SECONDS.labels(kind="autocomplete").time():
            with timings.measure("editor_assist"):
                route = _route_editor_assist(team, user, query, timings=timings)
                python_reason = route.reason
                autocomplete_response: HogQLAutocompleteResponse | None = None
                if (language_result := route.result) is not None:
                    try:
                        with timings.measure("response_mapping"):
                            autocomplete_response = _autocomplete_response_from_language_service(language_result)
                    except (AttributeError, KeyError, TypeError, ValueError):
                        logger.warning("hogql_language_service_invalid_autocomplete_response")
                        python_reason = "invalid_response"
                    else:
                        _record_editor_assist_backend(route, "autocomplete", "language_service", "served")
                    if autocomplete_response is None:
                        with timings.measure("fallback_error_tracking"):
                            _capture_malformed_language_service_response("autocomplete", "response_mapping")
                elif route.malformed_stage is not None:
                    with timings.measure("fallback_error_tracking"):
                        _capture_malformed_language_service_response("autocomplete", route.malformed_stage)
                if autocomplete_response is None:
                    database: Database | None = None
                    # Hog and template languages answer from globals, so building the schema is wasted work.
                    if query.language in (HogLanguage.HOG_QL, HogLanguage.HOG_QL_EXPR):
                        with timings.measure("fallback_database"):
                            _, database = resolve_database_for_connection(
                                team,
                                query.connectionId,
                                user=user,
                                error_factory=ValidationError,
                                modifiers=create_default_modifiers_for_team(team),
                                # Editor-assist only: query execution never reads cached sources.
                                use_cached_sources=True,
                            )
                    with timings.measure("fallback_python_autocomplete"):
                        autocomplete_response = get_hogql_autocomplete(
                            query=query, team=team, database_arg=database, user=user
                        )
                    _record_editor_assist_backend(route, "autocomplete", "python", python_reason)
            autocomplete_response.timings = [
                *(autocomplete_response.timings or []),
                *timings.to_list(back_out_stack=False),
            ]
            return autocomplete_response

    if isinstance(query, HogQLMetadata):
        with EDITOR_ASSIST_DURATION_SECONDS.labels(kind="metadata").time():
            route = _route_editor_assist(team, user, query)
            python_reason = route.reason
            if (language_result := route.result) is not None:
                try:
                    metadata_response = _metadata_response_from_language_service(query, language_result)
                except (AttributeError, KeyError, TypeError, ValueError):
                    logger.warning("hogql_language_service_invalid_metadata_response")
                    python_reason = "invalid_response"
                else:
                    _record_editor_assist_backend(route, "metadata", "language_service", "served")
                    return metadata_response
                _capture_malformed_language_service_response("metadata", "response_mapping")
            elif route.malformed_stage is not None:
                _capture_malformed_language_service_response("metadata", route.malformed_stage)
            metadata_query = HogQLMetadata.model_validate(query)
            metadata_response = get_hogql_metadata(query=metadata_query, team=team, user=user)
            _record_editor_assist_backend(route, "metadata", "python", python_reason)
            return metadata_response

    if isinstance(query, DatabaseSchemaQuery):
        return process_database_schema_query(team, query, user=user)

    query_runner = get_query_runner_or_none(
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
            pagination_cursor=pagination_cursor,
            analytics_props=analytics_props,
            allow_raw_results=allow_raw_results,
        )

    # This query doesn't run via query runner
    if hasattr(query, "source") and isinstance(query.source, BaseModel):
        return process_query_model(
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
    allow_raw_results: bool,
) -> dict | BaseModel | RawCachedQueryResponse:
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
