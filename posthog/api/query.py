import re
import uuid
import json
import time
import asyncio
from django.http import JsonResponse, StreamingHttpResponse
from drf_spectacular.utils import OpenApiResponse
from pydantic import BaseModel
from rest_framework import status, viewsets
from rest_framework.exceptions import NotAuthenticated, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from sentry_sdk import set_tag
from asgiref.sync import sync_to_async

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
    QueryStatusManager,
)
from posthog.clickhouse.query_tagging import tag_queries
from posthog.errors import ExposedCHQueryError
from posthog.hogql.ai import PromptUnclear, write_sql_from_prompt
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql_queries.apply_dashboard_filters import (
    apply_dashboard_filters_to_dict,
    apply_dashboard_variables_to_dict,
)
from posthog.hogql_queries.query_runner import ExecutionMode, execution_mode_from_refresh
from posthog.models.user import User
from posthog.rate_limit import (
    AIBurstRateThrottle,
    AISustainedRateThrottle,
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
        if query := self.request.data.get("query"):
            if isinstance(query, dict) and query.get("kind") == "HogQLQuery":
                return [HogQLQueryThrottle()]
        return [ClickHouseBurstRateThrottle(), ClickHouseSustainedRateThrottle()]

    @extend_schema(
        request=QueryRequest,
        responses={
            200: QueryResponseAlternative,
        },
    )
    @monitor(feature=Feature.QUERY, endpoint="query", method="POST")
    def create(self, request, *args, **kwargs) -> Response:
        data = self.get_model(request.data, QueryRequest)
        if data.filters_override is not None:
            data.query = apply_dashboard_filters_to_dict(
                data.query.model_dump(), data.filters_override.model_dump(), self.team
            )  # type: ignore

        if data.variables_override is not None:
            if isinstance(data.query, BaseModel):
                query_as_dict = data.query.model_dump()
            else:
                query_as_dict = data.query

            data.query = apply_dashboard_variables_to_dict(query_as_dict, data.variables_override, self.team)  # type: ignore

        client_query_id = data.client_query_id or uuid.uuid4().hex
        execution_mode = execution_mode_from_refresh(data.refresh)
        response_status: int = status.HTTP_200_OK

        self._tag_client_query_id(client_query_id)

        if data.async_:  # TODO: Legacy async, use "refresh=async" instead
            execution_mode = ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE

        if execution_mode == execution_mode.CACHE_ONLY_NEVER_CALCULATE:
            # Here in query endpoint we always want to calculate if the cache is stale
            execution_mode = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE

        tag_queries(query=request.data["query"])
        try:
            result = process_query_model(
                self.team,
                data.query,
                execution_mode=execution_mode,
                query_id=client_query_id,
                user=request.user,
            )
            if isinstance(result, BaseModel):
                result = result.model_dump(by_alias=True)
            if result.get("query_status") and result["query_status"].get("complete") is False:
                response_status = status.HTTP_202_ACCEPTED
            return Response(result, status=response_status)
        except (ExposedHogQLError, ExposedCHQueryError) as e:
            raise ValidationError(str(e), getattr(e, "code_name", None))
        except Exception as e:
            self.handle_column_ch_error(e)
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
        cancel_query(self.team.pk, pk)
        return Response(status=204)

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
        set_tag("client_query_id", query_id)


MAX_QUERY_TIMEOUT = 600


async def query_awaited(request: Request, *args, **kwargs) -> StreamingHttpResponse:
    """Async endpoint for handling event source queries using Server-Sent Events (SSE)."""

    # Call the create method on QueryViewSet, with the right accept header
    request.META["HTTP_ACCEPT"] = "application/json"
    view = await sync_to_async(QueryViewSet.as_view)({"post": "create"}, **kwargs)
    response = await sync_to_async(view)(request)

    if response.status_code != 202:  # Non-202 means we can return immediately
        response.render()
        content = response.rendered_content.decode("utf-8")
        return StreamingHttpResponse(
            [f"data: {content}\n\n".encode()],
            status=response.status_code,
            content_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    response.render()
    data = json.loads(response.rendered_content)

    async def event_stream():
        assert kwargs.get("team_id") is not None
        manager = QueryStatusManager(data["query_status"]["id"], cast(int, kwargs["team_id"]))
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
            try:
                status = await sync_to_async(manager.get_query_status)(show_progress=True)
                current_time = time.time()

                if isinstance(status, BaseModel) and getattr(status, "results", None):
                    yield f"data: {json.dumps(status.results)}\n\n".encode()
                    break
                elif isinstance(status, BaseModel):
                    # Only yield status updates every UPDATE_INTERVAL seconds
                    if current_time - last_update_time >= UPDATE_INTERVAL:
                        yield f"data: {status.model_dump_json(by_alias=True)}\n\n".encode()
                        # Force flush by yielding an empty bytes object
                        yield b""
                        last_update_time = current_time

            except Exception:
                capture_exception()
                yield f"data: {json.dumps({'error': 'Server error'})}\n\n".encode()
                break

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
        },
    )
