import re
from time import perf_counter
from typing import NoReturn

from django.core.cache import cache
from django.http import JsonResponse, StreamingHttpResponse

import orjson
import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse
from opentelemetry import trace
from prometheus_client import Counter
from pydantic import BaseModel
from rest_framework import status, viewsets
from rest_framework.exceptions import APIException, NotAuthenticated, Throttled, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import (
    HogQLQuery,
    HogQLQueryModifiers,
    LimitContext as SchemaLimitContext,
    QueryRequest,
    QueryResponseAlternative,
    QueryStatusResponse,
    QueryUpgradeRequest,
    QueryUpgradeResponse,
)

from posthog.hogql.ai import PromptUnclear, write_sql_from_prompt
from posthog.hogql.constants import LimitContext
from posthog.hogql.errors import ExposedHogQLError, ResolutionError
from posthog.hogql.metadata import enrich_hogql_validation_error

from posthog import settings
from posthog.api.documentation import _FallbackSerializer, extend_schema
from posthog.api.mixins import PydanticModelMixin
from posthog.api.monitoring import (
    Feature as MonitoringFeature,
    monitor,
)
from posthog.api.query_coalescer import QueryCoalescingMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.services.query import process_query_model
from posthog.api.streaming import sse_streaming_response
from posthog.api.utils import action, is_async_query, is_insight_actors_options_query, is_insight_actors_query
from posthog.clickhouse.client.execute_async import cancel_query, get_query_status
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.clickhouse.query_tagging import get_query_tag_value, get_query_tags, tag_queries
from posthog.constants import AvailableFeature
from posthog.errors import ExposedCHQueryError, InternalCHQueryError
from posthog.event_usage import EventSource, get_request_analytics_properties, report_user_or_team_action
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.apply_dashboard_filters import apply_dashboard_filters, apply_dashboard_variables
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode, execution_mode_from_refresh
from posthog.models.user import User
from posthog.models.utils import uuid7
from posthog.rate_limit import (
    AIBurstRateThrottle,
    AISustainedRateThrottle,
    APIQueriesBurstThrottle,
    APIQueriesSustainedThrottle,
    ClickHouseBurstRateThrottle,
    ClickHouseSustainedRateThrottle,
    HogQLQueryThrottle,
)
from posthog.rbac.user_access_control import UserAccessControlError
from posthog.schema_migrations.upgrade import upgrade

from common.hogvm.python.utils import HogVMException

logger = structlog.get_logger(__name__)

tracer = trace.get_tracer(__name__)

# Shown to the user when the org's concurrent-query limiter rejects a request. The raw limiter
# exception embeds an internal Redis key + task id, so we log that for debugging and surface this
# friendly message instead of leaking implementation details into the UI.
CONCURRENCY_LIMIT_USER_MESSAGE = "Too many queries are running right now — please try again in a moment."

QUERY_VALIDATION_ERROR_TOTAL = Counter(
    "posthog_query_validation_error_total",
    "Query validation failures returned from the query API.",
    labelnames=["query_type", "validation_code"],
)


def _extract_validation_code(error: ValidationError) -> str:
    validation_codes = error.get_codes()
    if isinstance(validation_codes, list):
        return validation_codes[0] if validation_codes and isinstance(validation_codes[0], str) else "unknown"
    if isinstance(validation_codes, dict):
        first_code = next(iter(validation_codes.values()), None)
        if isinstance(first_code, str):
            return first_code
        if isinstance(first_code, list) and first_code and isinstance(first_code[0], str):
            return first_code[0]
    return "unknown"


# Matches an absolute ISO date that carries an explicit time-of-day (e.g. `2026-07-09T00:00:00Z`,
# `2026-07-09 05:00:00`), but not a bare calendar day (`2026-07-09`) or a relative token (`-7d`, `mStart`).
_ISO_TIMESTAMP_WITH_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}")


def _date_bound_has_explicit_time(value: object) -> bool:
    return isinstance(value, str) and _ISO_TIMESTAMP_WITH_TIME_RE.match(value) is not None


def _mark_explicit_date_boundaries(query: BaseModel) -> None:
    """MCP query tools accept ISO timestamps in `dateRange.date_to`. When a caller passes a full
    timestamp with a time-of-day (e.g. `2026-07-09T00:00:00Z`) rather than a bare calendar day, they
    mean an exact boundary, so mark the range explicit instead of snapping `date_to` to end of day.

    Scoped to the MCP entrypoint on purpose: the web UI serialises fixed calendar ranges as naive
    `YYYY-MM-DDTHH:mm:ss` strings and relies on the default end-of-day rounding, so this must not
    change that path.
    """
    date_range = getattr(query, "dateRange", None)
    if date_range is None or not hasattr(date_range, "explicitDate") or date_range.explicitDate:
        return
    if _date_bound_has_explicit_time(getattr(date_range, "date_to", None)):
        date_range.explicitDate = True


def _process_query_request(
    request_data: QueryRequest, team, client_query_id: str | None = None, user=None
) -> tuple[BaseModel, str, ExecutionMode]:
    """Helper function to process query requests and return the necessary data for both sync and async endpoints."""
    query = request_data.query

    if request_data.filters_override is not None:
        query = apply_dashboard_filters(query, request_data.filters_override, team)

    if request_data.variables_override is not None:
        query = apply_dashboard_variables(query, request_data.variables_override, team)

    query_id = client_query_id or uuid7().hex
    execution_mode = execution_mode_from_refresh(request_data.refresh)

    if request_data.async_:  # TODO: Legacy async, use "refresh=async" instead
        execution_mode = ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE

    if execution_mode == ExecutionMode.CACHE_ONLY_NEVER_CALCULATE:
        # Here in query endpoint we always want to calculate if the cache is stale
        execution_mode = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE

    qt = get_query_tags()
    if request_data.name:
        qt.request_name = request_data.name
    elif hasattr(request_data.query, "name") and isinstance(request_data.query.name, str):
        qt.request_name = request_data.query.name
    qt.query = query.model_dump()

    return query, query_id, execution_mode


class QueryViewSet(QueryCoalescingMixin, TeamAndOrgViewSetMixin, PydanticModelMixin, viewsets.ViewSet):
    # NOTE: Do we need to override the scopes for the "create"
    scope_object = "query"
    serializer_class = _FallbackSerializer
    # Special case for query - these are all essentially read actions
    scope_object_read_actions = ["retrieve", "create", "list", "destroy"]
    scope_object_write_actions: list[str] = []
    sharing_enabled_actions = ["retrieve"]

    def get_throttles(self):
        if self.action == "draft_sql":
            return [AIBurstRateThrottle(), AISustainedRateThrottle()]
        if self.action == "get_query_log":
            return [APIQueriesBurstThrottle(), APIQueriesSustainedThrottle()]
        if (
            self.team_id in settings.API_QUERIES_PER_TEAM
            or (settings.API_QUERIES_ENABLED and self.check_team_api_queries_concurrency())
            or (settings.API_QUERIES_LEGACY_TEAM_LIST and self.team_id not in settings.API_QUERIES_LEGACY_TEAM_LIST)
        ):
            return [APIQueriesBurstThrottle(), APIQueriesSustainedThrottle()]
        if query := self.request.data.get("query"):
            if isinstance(query, dict) and query.get("kind") == "HogQLQuery":
                return [HogQLQueryThrottle()]
        return [ClickHouseBurstRateThrottle(), ClickHouseSustainedRateThrottle()]

    def check_team_api_queries_concurrency(self):
        cache_key = f"team/{self.team_id}/feature/{AvailableFeature.API_QUERIES_CONCURRENCY}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        if self.team:
            new_val = self.team.organization.is_feature_available(AvailableFeature.API_QUERIES_CONCURRENCY)
            cache.set(cache_key, new_val)
            return new_val
        return False

    def _raise_concurrency_throttled(self, exc: ConcurrencyLimitExceeded) -> NoReturn:
        # Log the raw detail (Redis key + task id) for Loki, but surface a clean message to the user.
        logger.warning("query_concurrency_limit_exceeded", detail=str(exc))
        raise Throttled(detail=CONCURRENCY_LIMIT_USER_MESSAGE)

    @extend_schema(
        request=QueryRequest,
        responses={
            200: QueryResponseAlternative,
        },
    )
    @monitor(feature=MonitoringFeature.QUERY, endpoint="query", method="POST")
    def create(self, request: Request, *args, **kwargs) -> Response:
        self._validate_query_kind(request, kwargs.get("query_kind"))
        start_time = perf_counter()
        with tracer.start_as_current_span("posthog.query.upgrade"):
            upgraded_query = upgrade(request.data)
        data = self.get_model(upgraded_query, QueryRequest)

        query = None
        try:
            query, client_query_id, execution_mode = _process_query_request(
                data, self.team, data.client_query_id, request.user
            )

            is_mcp_client = request.headers.get("x-posthog-client") == "mcp"
            if is_mcp_client:
                _mark_explicit_date_boundaries(query)

            self._tag_client_query_id(client_query_id)
            analytics_props = get_request_analytics_properties(request)
            query_dict = query.model_dump()

            if data.limit_context == SchemaLimitContext.POSTHOG_AI:
                limit_context: LimitContext | None = LimitContext.POSTHOG_AI
                # Max's insight tiles run in the browser, so the request looks like a session
                # web request and get_event_source classifies it as "web". Attribute it to
                # posthog_ai instead, matching the server-side executor's tagging.
                analytics_props["source"] = EventSource.POSTHOG_AI
            elif (
                is_async_query(query_dict)
                or is_insight_actors_query(query_dict)
                or is_insight_actors_options_query(query_dict)
            ) and get_query_tag_value("access_method") != "personal_api_key":
                # QUERY_ASYNC provides extended max execution time for insight queries
                limit_context = LimitContext.QUERY_ASYNC
            else:
                limit_context = None

            with tracer.start_as_current_span("posthog.query.process_query_model") as process_span:
                process_span.set_attribute("team_id", self.team.pk)
                process_span.set_attribute("query.kind", getattr(query, "kind", "Other"))
                process_span.set_attribute(
                    "query.is_query_service", get_query_tag_value("access_method") == "personal_api_key"
                )
                if limit_context is not None:
                    process_span.set_attribute("query.limit_context", limit_context.value)
                result = process_query_model(
                    self.team,
                    query,
                    execution_mode=execution_mode,
                    query_id=client_query_id,
                    user=request.user,  # type: ignore[arg-type]
                    is_query_service=(get_query_tag_value("access_method") == "personal_api_key"),
                    limit_context=limit_context,
                    analytics_props=analytics_props,
                )
                if isinstance(result, BaseModel):
                    result = result.model_dump(by_alias=True)

            total_time_ms = round((perf_counter() - start_time) * 1000, 2)
            try:
                with tracer.start_as_current_span("posthog.query.serialize_response") as serialize_span:
                    response_bytes = len(orjson.dumps(result))
                    serialize_span.set_attribute("response.bytes", response_bytes)
                report_user_or_team_action(
                    "query api response",
                    {
                        "query_type": getattr(query, "kind", "Other"),
                        "is_cached": result.get("is_cached", False),
                        "execution_mode": execution_mode.value,
                        "total_time_ms": total_time_ms,
                        "response_bytes": response_bytes,
                        "client_query_id": client_query_id,
                    },
                    user=request.user if isinstance(request.user, User) else None,
                    team=self.team,
                    organization=self.team.organization,
                    analytics_props=analytics_props,
                )
            except Exception:
                pass

            response_status = (
                status.HTTP_202_ACCEPTED
                if result.get("query_status") and result["query_status"].get("complete") is False
                else status.HTTP_200_OK
            )

            if is_mcp_client:
                with tracer.start_as_current_span("posthog.query.format_for_llm") as llm_span:
                    formatted = self._try_format_for_llm(query, result)
                    llm_span.set_attribute("query.formatted", formatted is not None)
                    if formatted is not None:
                        result["formatted_results"] = formatted

            return Response(result, status=response_status)
        except (ExposedHogQLError, ExposedCHQueryError, HogVMException) as e:
            detail = str(e)
            extra: dict | None = None
            if isinstance(e, ExposedHogQLError):
                request_user = request.user if isinstance(request.user, User) else None
                detail, extra = enrich_hogql_validation_error(query, self.team, request_user, detail)
            validation_error = ValidationError(detail, getattr(e, "code_name", None))
            if extra is not None:
                validation_error.extra = extra  # type: ignore[attr-defined]
            raise validation_error
        except InternalCHQueryError as e:
            self.handle_column_ch_error(e)
            capture_exception(e)
            raise APIException("ClickHouse error while executing query.")
        except UserAccessControlError as e:
            raise ValidationError(str(e))
        except ResolutionError as e:
            raise ValidationError(str(e))
        except ValidationError as e:
            query_type = getattr(query, "kind", "unknown")
            QUERY_VALIDATION_ERROR_TOTAL.labels(
                query_type=query_type,
                validation_code=_extract_validation_code(e),
            ).inc()
            raise
        except ConcurrencyLimitExceeded as c:
            self._raise_concurrency_throttled(c)
        except Exception as e:
            capture_exception(e)
            raise

    @extend_schema(
        description="(Experimental)",
        parameters=[OpenApiParameter("id", OpenApiTypes.STR, OpenApiParameter.PATH)],
        responses={200: QueryStatusResponse},
    )
    @monitor(feature=MonitoringFeature.QUERY, endpoint="query", method="GET")
    def retrieve(self, request: Request, pk=None, *args, **kwargs) -> JsonResponse:
        show_progress: bool = request.query_params.get("show_progress", False) == "true"
        show_progress = (
            show_progress or request.query_params.get("showProgress", False) == "true"
        )  # TODO: Remove this once we have a consistent naming convention
        query_status = get_query_status(team_id=self.team.pk, query_id=pk, show_progress=show_progress)
        query_status_response = QueryStatusResponse(query_status=query_status)

        http_code: int = status.HTTP_202_ACCEPTED
        if query_status.error:
            if query_status.error_message:
                http_code = status.HTTP_400_BAD_REQUEST  # An error where a user can likely take an action to resolve it
            else:
                http_code = status.HTTP_500_INTERNAL_SERVER_ERROR  # An internal surprise
        elif query_status.complete:
            http_code = status.HTTP_200_OK

        return JsonResponse(query_status_response.model_dump(), safe=False, status=http_code)

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(methods=["POST"], detail=False)
    def check_auth_for_async(self, request: Request, *args, **kwargs):
        return JsonResponse({"user": "ok"}, status=status.HTTP_200_OK)

    @extend_schema(
        description="(Experimental)",
        responses={
            204: OpenApiResponse(description="Query cancelled"),
        },
    )
    @monitor(feature=MonitoringFeature.QUERY, endpoint="query", method="DELETE")
    def destroy(self, request, pk=None, *args, **kwargs):
        dequeue_only = request.query_params.get("dequeue_only", False) == "true"
        message = cancel_query(self.team.pk, pk, dequeue_only=dequeue_only)

        return Response(status=200, data={"message": message})

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(methods=["GET"], detail=False)
    def draft_sql(self, request: Request, *args, **kwargs) -> Response:
        if not isinstance(request.user, User):
            raise NotAuthenticated()
        prompt = request.GET.get("prompt")
        current_query = request.GET.get("current_query")
        if not prompt:
            raise ValidationError({"prompt": ["This field is required."]}, code="required")
        if len(prompt) > 400:
            raise ValidationError({"prompt": ["This field is too long."]}, code="too_long")
        try:
            result = write_sql_from_prompt(
                prompt, current_query=current_query, user=request.user, team=self.team, request=request
            )
        except PromptUnclear as e:
            raise ValidationError({"prompt": [str(e)]}, code="unclear")
        return Response({"sql": result})

    @extend_schema(
        request=QueryUpgradeRequest,
        responses={
            200: QueryUpgradeResponse,
        },
        description="Upgrades a query without executing it. Returns a query with all nodes migrated to the latest version.",
    )
    @action(methods=["POST"], detail=False, url_path="upgrade")
    def upgrade(self, request: Request, *args, **kwargs) -> Response:
        upgraded_query = upgrade(request.data)
        return Response({"query": upgraded_query["query"]}, status=200)

    @extend_schema(
        description="Get query log details from query_log_archive table for a specific query_id, the query must have been issued in last 24 hours.",
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(methods=["GET"], detail=True, url_path="log")
    def get_query_log(self, request: Request, pk: str, *args, **kwargs) -> Response:
        try:
            query = HogQLQuery(
                query="select * from query_log where query_id = {client_query_id} and event_date >= yesterday()",
                values={
                    "client_query_id": pk,
                },
                name="get_query_log",
            )
            hogql_runner = HogQLQueryRunner(
                query=query,
                team=self.team,
                modifiers=HogQLQueryModifiers(),
                limit_context=LimitContext.QUERY,
            )
            result = hogql_runner.calculate()
            return Response(result.model_dump(), status=200)
        except ConcurrencyLimitExceeded as c:
            self._raise_concurrency_throttled(c)
        except Exception as e:
            capture_exception(e)
            raise

    def handle_column_ch_error(self, error):
        if getattr(error, "message", None):
            match = re.search(r"There's no column.*in table", error.message)
            if match:
                # TODO: remove once we support all column types
                raise ValidationError(
                    match.group(0) + ". Note: While in beta, not all column types may be fully supported"
                )
        return

    def _tag_client_query_id(self, query_id: str | None):
        if query_id is None:
            return

        tag_queries(client_query_id=query_id)

    @extend_schema(operation_id="query_create_with_kind")
    @action(methods=["POST"], detail=False, url_path=r"(?P<query_kind>[A-Z][A-Za-z]*)")
    def create_with_kind(self, request: Request, *args, **kwargs) -> Response:
        return self.create(request, *args, **kwargs)

    def _validate_query_kind(self, request: Request, query_kind: str | None) -> None:
        if not query_kind:
            return
        if not isinstance(request.data, dict):
            raise ValidationError("Query body must be a JSON object.")
        query_payload = request.data.get("query")
        if query_payload is not None and not isinstance(query_payload, dict):
            raise ValidationError("Query must be a JSON object.")
        body_kind = query_payload.get("kind") if isinstance(query_payload, dict) else None
        if query_kind != body_kind:
            raise ValidationError(
                f'Query kind mismatch: path kind "{query_kind}" does not match body kind "{body_kind}".'
            )

    def _try_format_for_llm(self, query: BaseModel, result: dict) -> str | None:
        """Try to format query results as LLM-friendly text. Returns None on failure."""
        if not settings.EE_AVAILABLE:
            return None
        try:
            from ee.hogai.context.insight.format import format_query_results_for_llm

            return format_query_results_for_llm(query, result, self.team)
        except Exception:
            logger.warning("mcp_llm_format_failed", exc_info=True)
            return None


MAX_QUERY_TIMEOUT = 600


async def progress(request: Request, *args, **kwargs) -> StreamingHttpResponse:
    # TEMPORARY endpoint to avoid breaking changes

    return sse_streaming_response(
        [], endpoint="query_progress_stub", status=status.HTTP_200_OK, headers={"Connection": "keep-alive"}
    )
