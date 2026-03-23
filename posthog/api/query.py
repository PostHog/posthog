import re
from time import perf_counter
from typing import Optional

from django.core.cache import cache
from django.http import JsonResponse, StreamingHttpResponse

import orjson
import structlog
import posthoganalytics
from drf_spectacular.utils import OpenApiResponse
from pydantic import BaseModel
from redis.exceptions import RedisError
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

from posthog import settings
from posthog.api.documentation import extend_schema
from posthog.api.mixins import PydanticModelMixin
from posthog.api.monitoring import Feature, monitor
from posthog.api.query_coalescer import CoalesceSignal, QueryCoalescer, compute_coalescing_key
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.services.query import process_query_model
from posthog.api.utils import action, is_insight_actors_options_query, is_insight_actors_query, is_insight_query
from posthog.clickhouse.client.execute_async import cancel_query, get_query_status
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.clickhouse.query_tagging import get_query_tag_value, get_query_tags, tag_queries
from posthog.constants import AvailableFeature
from posthog.errors import ExposedCHQueryError, InternalCHQueryError
from posthog.event_usage import get_request_analytics_properties, report_user_or_team_action
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


class QueryViewSet(TeamAndOrgViewSetMixin, PydanticModelMixin, viewsets.ViewSet):
    # NOTE: Do we need to override the scopes for the "create"
    scope_object = "query"
    # Special case for query - these are all essentially read actions
    scope_object_read_actions = ["retrieve", "create", "list", "destroy"]
    scope_object_write_actions: list[str] = []
    sharing_enabled_actions = ["retrieve"]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._coalescer: Optional[QueryCoalescer] = None

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

    def _try_coalesce(
        self, query: BaseModel, execution_mode: ExecutionMode, client_query_id: str
    ) -> tuple[Optional[Response], ExecutionMode]:
        """Attempt query coalescing.

        Returns a (response, execution_mode) tuple.  The response is non-None only
        when a follower must short-circuit (e.g. replay an error or report a timeout).
        The returned execution_mode may differ from the input: force_blocking followers
        are downgraded to blocking so they hit the cache populated by the leader.
        """
        # Coalescing applies to both regular blocking queries and force_blocking queries.
        # force_blocking followers are downgraded to RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
        # on DONE so they read from the cache the leader just populated, rather than recalculating.
        if execution_mode not in (
            ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
            ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
        ):
            return None, execution_mode

        enabled = posthoganalytics.feature_enabled(
            "http-query-coalescing",
            str(self.team.pk),
        )

        query_json = query.model_dump_json()
        key = compute_coalescing_key(self.team.pk, query_json)
        coalescer = QueryCoalescer(key, dry_run=not enabled)

        log = logger.bind(coalescing_key=key, query_id=client_query_id)

        # Dry run: all requests still compete for the lock so we can measure how many
        # concurrent duplicates exist (follower_dry_run metric). Leaders proceed normally
        # (the Redis overhead is minimal). Followers return immediately without waiting.
        try:
            is_leader = coalescer.try_acquire()
        except RedisError:
            log.warning("query_coalescing_redis_error", msg="redis unavailable, skipping coalescing")
            return None, execution_mode

        if is_leader:
            log.info("query_coalescing_leader_start")
            self._coalescer = coalescer
            return None, execution_mode

        if not enabled:
            return None, execution_mode

        # Follower path
        log.info("query_coalescing_follower_waiting")

        signal = coalescer.wait_for_signal(max_wait=settings.QUERY_COALESCING_MAX_WAIT_SECONDS)

        if signal == CoalesceSignal.DONE:
            log.info("query_coalescing_follower_done")
            # Followers fall through to cache-aware mode so they read the result
            # the leader just wrote, instead of recalculating.
            return None, ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE

        if signal == CoalesceSignal.ERROR:
            error_data = coalescer.get_error_response()
            if error_data:
                log.info("query_coalescing_follower_replaying_error", status=error_data["status"])
                try:
                    body = orjson.loads(error_data["body"])
                except Exception:
                    log.warning("query_coalescing_follower_body_parse_failed")
                    return None, execution_mode
                return Response(
                    data=body,
                    status=error_data["status"],
                ), execution_mode
            # Couldn't read error, fall through
            log.warning("query_coalescing_follower_error_read_failed")
            return None, execution_mode

        if signal == CoalesceSignal.TIMEOUT:
            log.warning("query_coalescing_follower_timeout")
            return Response(
                data={"type": "server_error", "detail": "Query is still running, please try again shortly."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ), execution_mode

        log.info("query_coalescing_follower_fallthrough", signal=signal)
        return None, execution_mode

    def finalize_response(self, request, response, *args, **kwargs):
        try:
            response = super().finalize_response(request, response, *args, **kwargs)
        finally:
            if self._coalescer and self._coalescer.is_leader:
                try:
                    if response.status_code >= 400:
                        response.render()
                        self._coalescer.store_error_response(response.status_code, response.content)
                    else:
                        self._coalescer.mark_done()
                except Exception:
                    logger.warning("query_coalescing_finalize_error", exc_info=True)
                finally:
                    self._coalescer.cleanup()

        return response

    @extend_schema(
        request=QueryRequest,
        responses={
            200: QueryResponseAlternative,
        },
    )
    @monitor(feature=Feature.QUERY, endpoint="query", method="POST")
    def create(self, request: Request, *args, **kwargs) -> Response:
        start_time = perf_counter()
        upgraded_query = upgrade(request.data)
        data = self.get_model(upgraded_query, QueryRequest)

        try:
            query, client_query_id, execution_mode = _process_query_request(
                data, self.team, data.client_query_id, request.user
            )

            error, execution_mode = self._try_coalesce(query, execution_mode, client_query_id)
            if error is not None:
                return error

            self._tag_client_query_id(client_query_id)
            analytics_props = get_request_analytics_properties(request)
            query_dict = query.model_dump()

            if data.limit_context == SchemaLimitContext.POSTHOG_AI:
                limit_context: LimitContext | None = LimitContext.POSTHOG_AI
            elif (
                is_insight_query(query_dict)
                or is_insight_actors_query(query_dict)
                or is_insight_actors_options_query(query_dict)
            ) and get_query_tag_value("access_method") != "personal_api_key":
                # QUERY_ASYNC provides extended max execution time for insight queries
                limit_context = LimitContext.QUERY_ASYNC
            else:
                limit_context = None

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
                response_bytes = len(orjson.dumps(result))
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
            return Response(result, status=response_status)
        except (ExposedHogQLError, ExposedCHQueryError, HogVMException) as e:
            raise ValidationError(str(e), getattr(e, "code_name", None))
        except InternalCHQueryError as e:
            self.handle_column_ch_error(e)
            capture_exception(e)
            raise APIException("ClickHouse error while executing query.")
        except UserAccessControlError as e:
            raise ValidationError(str(e))
        except ResolutionError as e:
            raise ValidationError(str(e))
        except ConcurrencyLimitExceeded as c:
            raise Throttled(detail=str(c))
        except Exception as e:
            capture_exception(e)
            raise

    @extend_schema(
        description="(Experimental)",
        responses={200: QueryStatusResponse},
    )
    @monitor(feature=Feature.QUERY, endpoint="query", method="GET")
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

    @action(methods=["POST"], detail=False)
    def check_auth_for_async(self, request: Request, *args, **kwargs):
        return JsonResponse({"user": "ok"}, status=status.HTTP_200_OK)

    @extend_schema(
        description="(Experimental)",
        responses={
            204: OpenApiResponse(description="Query cancelled"),
        },
    )
    @monitor(feature=Feature.QUERY, endpoint="query", method="DELETE")
    def destroy(self, request, pk=None, *args, **kwargs):
        dequeue_only = request.query_params.get("dequeue_only", False) == "true"
        message = cancel_query(self.team.pk, pk, dequeue_only=dequeue_only)

        return Response(status=200, data={"message": message})

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
        responses={200: "Query log details"},
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
            raise Throttled(detail=str(c))
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


MAX_QUERY_TIMEOUT = 600


async def progress(request: Request, *args, **kwargs) -> StreamingHttpResponse:
    # TEMPORARY endpoint to avoid breaking changes

    return StreamingHttpResponse(
        [],
        status=status.HTTP_200_OK,
        content_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
