import re
import uuid
import json
import time
import asyncio

from django.core.cache import cache
from django.http import JsonResponse, StreamingHttpResponse
from drf_spectacular.utils import OpenApiResponse
from pydantic import BaseModel
from rest_framework import status, viewsets
from rest_framework.exceptions import NotAuthenticated, ValidationError, Throttled
from rest_framework.request import Request
from rest_framework.response import Response
from asgiref.sync import sync_to_async
from concurrent.futures import ThreadPoolExecutor

from posthog.clickhouse.client.connection import Workload
from posthog import settings
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.constants import AvailableFeature
from posthog.exceptions_capture import capture_exception
from posthog.api.documentation import extend_schema
from posthog.api.mixins import PydanticModelMixin
from posthog.api.monitoring import Feature, monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.services.query import process_query_model

from posthog.api.utils import action
from posthog.clickhouse.client.execute_async import (
    cancel_query,
    get_query_status,
)
from posthog.clickhouse.query_tagging import tag_queries, get_query_tag_value
from posthog.errors import ExposedCHQueryError
from posthog.hogql.ai import PromptUnclear, write_sql_from_prompt
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql_queries.apply_dashboard_filters import (
    apply_dashboard_filters,
    apply_dashboard_variables,
)
from posthog.hogql_queries.query_runner import ExecutionMode, execution_mode_from_refresh
from posthog.models.user import User
from posthog.rate_limit import (
    AIBurstRateThrottle,
    AISustainedRateThrottle,
    APIQueriesBurstThrottle,
    APIQueriesSustainedThrottle,
    ClickHouseBurstRateThrottle,
    ClickHouseSustainedRateThrottle,
    HogQLQueryThrottle,
)
from posthog.schema import (
    QueryRequest,
    QueryResponseAlternative,
    QueryStatusResponse,
    ClickhouseQueryProgress,
)
from posthog.hogql.constants import LimitContext
from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.client.connection import default_client

# Create a dedicated thread pool for query processing
# Setting max_workers to ensure we don't overwhelm the system
# while still allowing concurrent queries
QUERY_EXECUTOR = ThreadPoolExecutor(
    max_workers=50,  # 50 should be enough to have 200 simultaneous queries across clickhouse
    thread_name_prefix="query_processor",
)


def _process_query_request(
    request_data: QueryRequest, team, client_query_id: str | None = None, user=None
) -> tuple[BaseModel, str, ExecutionMode]:
    """Helper function to process query requests and return the necessary data for both sync and async endpoints."""
    query = request_data.query

    if request_data.filters_override is not None:
        query = apply_dashboard_filters(query, request_data.filters_override, team)

    if request_data.variables_override is not None:
        query = apply_dashboard_variables(query, request_data.variables_override, team)

    query_id = client_query_id or uuid.uuid4().hex
    execution_mode = execution_mode_from_refresh(request_data.refresh)

    if request_data.async_:  # TODO: Legacy async, use "refresh=async" instead
        execution_mode = ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE

    if execution_mode == ExecutionMode.CACHE_ONLY_NEVER_CALCULATE:
        # Here in query endpoint we always want to calculate if the cache is stale
        execution_mode = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE

    tag_queries(query=query.model_dump())

    return query, query_id, execution_mode


class QueryViewSet(TeamAndOrgViewSetMixin, PydanticModelMixin, viewsets.ViewSet):
    # NOTE: Do we need to override the scopes for the "create"
    scope_object = "query"
    # Special case for query - these are all essentially read actions
    scope_object_read_actions = ["retrieve", "create", "list", "destroy"]
    scope_object_write_actions: list[str] = []
    sharing_enabled_actions = ["retrieve"]

    def get_throttles(self):
        if self.action == "draft_sql":
            return [AIBurstRateThrottle(), AISustainedRateThrottle()]
        if self.team_id in settings.API_QUERIES_PER_TEAM or (
            settings.API_QUERIES_ENABLED and self.check_team_api_queries_concurrency()
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

    @extend_schema(
        request=QueryRequest,
        responses={
            200: QueryResponseAlternative,
        },
    )
    @monitor(feature=Feature.QUERY, endpoint="query", method="POST")
    def create(self, request: Request, *args, **kwargs) -> Response:
        data = self.get_model(request.data, QueryRequest)
        try:
            query, client_query_id, execution_mode = _process_query_request(
                data, self.team, data.client_query_id, request.user
            )
            self._tag_client_query_id(client_query_id)

            result = process_query_model(
                self.team,
                query,
                execution_mode=execution_mode,
                query_id=client_query_id,
                user=request.user,  # type: ignore[arg-type]
                is_query_service=(get_query_tag_value("access_method") == "personal_api_key"),
                limit_context=(
                    # QUERY_ASYNC provides extended max execution time for insight queries
                    LimitContext.QUERY_ASYNC
                    if is_insight_query(query) and get_query_tag_value("access_method") != "personal_api_key"
                    else None
                ),
            )
            if isinstance(result, BaseModel):
                result = result.model_dump(by_alias=True)
            response_status = (
                status.HTTP_202_ACCEPTED
                if result.get("query_status") and result["query_status"].get("complete") is False
                else status.HTTP_200_OK
            )
            return Response(result, status=response_status)
        except (ExposedHogQLError, ExposedCHQueryError) as e:
            raise ValidationError(str(e), getattr(e, "code_name", None))
        except ConcurrencyLimitExceeded as c:
            raise Throttled(detail=str(c))
        except Exception as e:
            self.handle_column_ch_error(e)
            capture_exception(e)
            raise

    def auth_for_awaiting(self, request: Request, *args, **kwargs):
        # Parse the request data here so we don't need to read the body again
        try:
            # Get the raw Django request to access its body
            return JsonResponse(
                {"user": "ok", "data": request.data, "team_id": self.team.pk}, status=status.HTTP_200_OK
            )
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=status.HTTP_400_BAD_REQUEST)

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

    @action(methods=["GET"], detail=False)
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
            result = write_sql_from_prompt(prompt, current_query=current_query, user=request.user, team=self.team)
        except PromptUnclear as e:
            raise ValidationError({"prompt": [str(e)]}, code="unclear")
        return Response({"sql": result})

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


async def progress(request: Request, *args, **kwargs) -> StreamingHttpResponse:
    """
    Stream query progress updates using Server-Sent Events (SSE).
    This endpoint will continuously send progress updates until the query completes or times out.
    """

    # Call the auth check method on QueryViewSet
    request.META["HTTP_ACCEPT"] = "application/json"
    view = await sync_to_async(QueryViewSet.as_view)({"get": "auth_for_awaiting"}, team_id=kwargs["team_id"])
    response = await sync_to_async(view)(request)

    if response.status_code != 200:  # Non-200 means we can return immediately, likely error
        response.render()
        content = response.rendered_content.decode("utf-8")
        return StreamingHttpResponse(
            [f"data: {content}\n\n".encode()],
            status=response.status_code,
            content_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    async def event_stream():
        start_time = time.time()

        # For things to feel snappy we want to frequently check initially, then back off
        POLL_INTERVAL = 1
        QUERY_START_TIMEOUT = 10  # query needs to start within 10 seconds
        QUERY = (
            lambda table: f"""
        SELECT
            read_rows,
            read_bytes,
            total_rows_approx,
            elapsed,
            memory_usage,
            hostname() as host
        FROM {table}
        WHERE query_id LIKE %(query_id)s and query LIKE %(user_id)s
        LIMIT 1
        SETTINGS max_execution_time = 5
        """
        )
        QUERY_PARAMS = {
            "cluster": settings.CLICKHOUSE_CLUSTER,
            "query_id": f"{request.user.id}_{kwargs['query_id']}_%",
            "user_id": f"/* user_id:{request.user.id} %",
        }
        try:
            while time.time() - start_time < QUERY_START_TIMEOUT:
                # First query the distributed table to find the initiatorhost, then only query the host from then on
                results = await sync_to_async(sync_execute)(
                    QUERY("distributed_system_processes"),
                    QUERY_PARAMS,
                    workload=Workload.ONLINE,
                )
                if results and len(results) > 0:
                    break
                else:
                    await asyncio.sleep(POLL_INTERVAL)

            if results:
                while time.time() - start_time < MAX_QUERY_TIMEOUT:
                    progress = ClickhouseQueryProgress(
                        rows_read=int(results[0][0]),
                        bytes_read=int(results[0][1]),
                        estimated_rows_total=int(results[0][2]),
                        memory_usage=int(results[0][4]),
                        time_elapsed=int(results[0][3]),
                    )

                    yield f"data: {progress.model_dump_json()}\n\n".encode()
                    await asyncio.sleep(POLL_INTERVAL)

                    with default_client(host=results[0][5]) as client:
                        results = sync_execute(
                            QUERY("system.processes"),
                            QUERY_PARAMS,
                            sync_client=client,
                        )
                        if not results or len(results) == 0:
                            break

            else:
                yield f"data: {json.dumps({'error': 'No running query found with this ID'})}\n\n".encode()

        except Exception as e:
            capture_exception(e)
            yield f"data: {json.dumps({'error': 'Error fetching query progress'})}\n\n".encode()

    return StreamingHttpResponse(
        event_stream(),
        content_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


MAX_QUERY_TIMEOUT = 600


def is_insight_query(query):
    insight_kinds = {
        "TrendsQuery",
        "FunnelsQuery",
        "RetentionQuery",
        "PathsQuery",
        "StickinessQuery",
        "LifecycleQuery",
    }
    if getattr(query, "kind", None) in insight_kinds:
        return True
    if getattr(query, "kind", None) == "HogQLQuery":
        return True
    if getattr(query, "kind", None) == "DataTableNode":
        source = getattr(query, "source", None)
        if source and getattr(source, "kind", None) in insight_kinds:
            return True
    if getattr(query, "kind", None) == "DataVisualizationNode":
        source = getattr(query, "source", None)
        if source and getattr(source, "kind", None) in insight_kinds:
            return True
    return False
