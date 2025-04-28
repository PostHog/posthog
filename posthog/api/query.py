import re
import uuid
import json
import time
import asyncio
from contextlib import suppress

import structlog
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

from posthog import settings
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.constants import AvailableFeature
from posthog.exceptions_capture import capture_exception
from posthog.api.documentation import extend_schema
from posthog.api.mixins import PydanticModelMixin
from posthog.api.monitoring import Feature, monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.services.query import process_query_model
from posthog.models.team import Team
from django.contrib.auth.models import AnonymousUser

from posthog.api.utils import action
from posthog.clickhouse.client.execute_async import (
    cancel_query,
    get_query_status,
    QueryStatusManager,
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
)
from typing import cast

# Create a dedicated thread pool for query processing
# Setting max_workers to ensure we don't overwhelm the system
# while still allowing concurrent queries
QUERY_EXECUTOR = ThreadPoolExecutor(
    max_workers=50,  # 50 should be enough to have 200 simultaneous queries across clickhouse
    thread_name_prefix="query_processor",
)

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
        with suppress(Exception):
            request_id = structlog.get_context(logger).get("request_id")
            if request_id:
                uuid.UUID(request_id)  # just to verify it is a real UUID
                tag_queries(http_request_id=request_id)
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


MAX_QUERY_TIMEOUT = 600


async def query_awaited(request: Request, *args, **kwargs) -> StreamingHttpResponse:
    """Async endpoint for handling event source queries using Server-Sent Events (SSE)."""

    # Call the auth check method on QueryViewSet
    request.META["HTTP_ACCEPT"] = "application/json"
    view = await sync_to_async(QueryViewSet.as_view)({"post": "auth_for_awaiting"}, **kwargs)
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

    try:
        # Get the parsed data from the auth response
        auth_content = json.loads(response.content)
        json_data = auth_content["data"]
        data = QueryRequest.model_validate(json_data)
        team = await Team.objects.aget(pk=auth_content["team_id"])
        query, client_query_id, execution_mode = await sync_to_async(_process_query_request)(
            data,
            team,
            data.client_query_id,
            request.user,
        )
        if execution_mode in (ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE):
            execution_mode = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
        elif execution_mode == ExecutionMode.CALCULATE_ASYNC_ALWAYS:
            execution_mode = ExecutionMode.CALCULATE_BLOCKING_ALWAYS

        # Define an async wrapper for process_query_model using sync_to_async
        # This provides better handling of task cancellation than run_in_executor
        async_process_query_model = sync_to_async(
            process_query_model,
        )

        # Create a task from the async wrapper
        query_task = asyncio.create_task(
            async_process_query_model(
                team=team,
                query=query,
                execution_mode=execution_mode,
                query_id=client_query_id,
                user=request.user if not isinstance(request.user, AnonymousUser) else None,
                is_query_service=(get_query_tag_value("access_method") == "personal_api_key"),
            )
        )

        # YOLO give the task a moment to materialize (otherwise the task looks like it's been cancelled)
        await asyncio.sleep(0.5)

        async def event_stream():
            assert kwargs.get("team_id") is not None
            manager = QueryStatusManager(client_query_id, cast(int, kwargs["team_id"]))
            start_time = time.time()
            last_update_time: float = start_time

            # For things to feel snappy we want to frequently check initially, then back off so we don't overload redis
            FAST_POLL_DURATION = 3.0  # First 3 seconds
            MEDIUM_POLL_DURATION = 15.0  # Until 15 seconds
            FAST_POLL_INTERVAL = 0.05
            MEDIUM_POLL_INTERVAL = 0.1
            SLOW_POLL_INTERVAL = 1.0
            UPDATE_INTERVAL = 1.0  # How often to send updates to client

            while time.time() - start_time < MAX_QUERY_TIMEOUT:
                # Check if the query task has completed
                if query_task.done():
                    if query_task.cancelled():
                        # Explicitly check for cancellation first
                        yield f"data: {json.dumps({'error': 'Query was cancelled', 'status_code': 499})}\n\n".encode()
                        capture_exception(Exception("Query was cancelled"))
                        break
                    try:
                        result = query_task.result()
                    except asyncio.CancelledError as e:
                        # Handle the cancellation as an SSE event
                        yield f"data: {json.dumps({'error': 'Query was cancelled', 'status_code': 499})}\n\n".encode()
                        capture_exception(e)
                        break
                    except (ExposedHogQLError, ExposedCHQueryError) as e:
                        yield f"data: {json.dumps({'error': str(e), 'status_code': 400})}\n\n".encode()
                        break
                    except Exception as e:
                        # Include error details for better debugging
                        error_message = str(e)
                        yield f"data: {json.dumps({'error': f'Server error: {error_message}'})}\n\n".encode()
                        capture_exception(e)
                        break

                    if isinstance(result, BaseModel):
                        yield f"data: {result.model_dump_json(by_alias=True)}\n\n".encode()
                    else:
                        yield f"data: {json.dumps(result)}\n\n".encode()
                    break

                try:
                    # Try to get a status updates while waiting
                    current_time = time.time()
                    if current_time - last_update_time >= UPDATE_INTERVAL:
                        status = await sync_to_async(manager.get_clickhouse_progresses)()

                        if isinstance(status, BaseModel):
                            status_update = {"complete": False, **status.model_dump(by_alias=True)}
                            yield f"data: {json.dumps(status_update)}\n\n".encode()
                            last_update_time = current_time
                # Just ignore errors when getting progress, shouldn't impact users
                except Exception as e:
                    capture_exception(e)

                elapsed_time = time.time() - start_time
                if elapsed_time < FAST_POLL_DURATION:
                    await asyncio.sleep(FAST_POLL_INTERVAL)
                elif elapsed_time < MEDIUM_POLL_DURATION:
                    await asyncio.sleep(MEDIUM_POLL_INTERVAL)
                else:
                    await asyncio.sleep(SLOW_POLL_INTERVAL)

        return StreamingHttpResponse(
            event_stream(),
            content_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )
    except (ExposedHogQLError, ExposedCHQueryError) as e:
        error_response = f"data: {json.dumps({'error': str(e)})}\n\n".encode()
        return StreamingHttpResponse(
            [error_response],
            content_type="text/event-stream",
            status=status.HTTP_400_BAD_REQUEST,
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )
