import re
import uuid

from django.http import JsonResponse
from drf_spectacular.utils import OpenApiResponse
from pydantic import BaseModel
from posthog.hogql_queries.query_runner import ExecutionMode, execution_mode_from_refresh
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError, NotAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from sentry_sdk import capture_exception
from rest_framework import status

from posthog.api.documentation import extend_schema
from posthog.api.mixins import PydanticModelMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.services.query import process_query_model
from posthog.clickhouse.client.execute_async import (
    cancel_query,
    get_query_status,
)
from posthog.clickhouse.query_tagging import tag_queries
from posthog.errors import ExposedCHQueryError
from posthog.hogql.ai import PromptUnclear, write_sql_from_prompt
from posthog.hogql.errors import ExposedHogQLError
from posthog.models.user import User
from posthog.rate_limit import (
    AIBurstRateThrottle,
    AISustainedRateThrottle,
    TeamRateThrottle,
)
from posthog.schema import QueryRequest, QueryResponseAlternative, QueryStatusResponse


class QueryThrottle(TeamRateThrottle):
    scope = "query"
    rate = "120/hour"


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
        else:
            return [QueryThrottle()]

    @extend_schema(
        request=QueryRequest,
        responses={
            200: QueryResponseAlternative,
        },
    )
    def create(self, request, *args, **kwargs) -> Response:
        data = self.get_model(request.data, QueryRequest)
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
    def retrieve(self, request: Request, pk=None, *args, **kwargs) -> JsonResponse:
        query_status = get_query_status(
            team_id=self.team.pk, query_id=pk, show_progress=request.query_params.get("showProgress", False)
        )
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

    @extend_schema(
        description="(Experimental)",
        responses={
            204: OpenApiResponse(description="Query cancelled"),
        },
    )
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
