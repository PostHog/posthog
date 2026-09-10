import uuid
from typing import cast

import posthoganalytics
from drf_spectacular.utils import OpenApiResponse
from langchain_core.runnables import RunnableConfig
from posthoganalytics.ai.langchain.callbacks import CallbackHandler
from rest_framework import serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer, extend_schema
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle


class FixHogQLRequestSerializer(serializers.Serializer):
    query = serializers.CharField(
        help_text="The HogQL query to work on.",
    )
    error = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="The error the query returned. When set, the tool fixes that error and changes nothing else.",
    )
    connection_id = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text=(
            "Id of the data warehouse connection the query runs against, so the tool sees that "
            "connection's tables instead of only the ClickHouse catalog."
        ),
    )


class FixHogQLResponseSerializer(serializers.Serializer):
    query = serializers.CharField(help_text="The updated HogQL query.")
    trace_id = serializers.CharField(help_text="Id of the LLM trace, for support and debugging.")


class FixHogQLErrorSerializer(serializers.Serializer):
    error = serializers.CharField(help_text="Why the query could not be updated.")
    trace_id = serializers.CharField(help_text="Id of the LLM trace, for support and debugging.")


class FixHogQLViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    serializer_class = _FallbackSerializer
    # Every request runs an LLM, so this endpoint carries the same budget as the other AI ones.
    throttle_classes = [AIBurstRateThrottle, AISustainedRateThrottle]

    @extend_schema(operation_id="fix_hogql_list")
    def list(self, request: Request, *args, **kwargs) -> Response:
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    @validated_request(
        FixHogQLRequestSerializer,
        responses={
            200: OpenApiResponse(response=FixHogQLResponseSerializer, description="The updated query."),
            400: OpenApiResponse(response=FixHogQLErrorSerializer, description="The query could not be updated."),
        },
        summary="Fix a HogQL query",
    )
    def create(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        from products.data_warehouse.backend.facade.api import HogQLQueryFixerTool

        query = request.validated_data["query"]
        error = request.validated_data["error"]
        connection_id = request.validated_data["connection_id"]

        trace_id = f"fix_hogql_query_{uuid.uuid4()}"
        user = cast(User, request.user)

        fix_hogql_context: dict[str, str] = {
            "hogql_query": query,
            "error_message": error,
        }
        # Only present when the query targets a direct-query data warehouse connection, so the fixer
        # sees that connection's tables instead of only the ClickHouse catalog.
        if connection_id:
            fix_hogql_context["connection_id"] = connection_id

        config: RunnableConfig = {
            "configurable": {
                "contextual_tools": {
                    "fix_hogql_query": fix_hogql_context,
                },
                "team": self.team,
                "user": user,
                "trace_id": trace_id,
                "distinct_id": user.distinct_id,
            },
            "callbacks": (
                [CallbackHandler(posthoganalytics.default_client, distinct_id=user.distinct_id, trace_id=trace_id)]
                if posthoganalytics.default_client
                else None
            ),
        }

        result = HogQLQueryFixerTool(
            team=self.team, user=user, config=config, tool_call_id="fix_hogql_query_tool_call_id"
        ).invoke({})

        if result is None or (isinstance(result, str) and len(result) == 0):
            return Response({"trace_id": trace_id, "error": "Could not fix the query"}, status=400)

        return Response({"query": result, "trace_id": trace_id}, status=200)
