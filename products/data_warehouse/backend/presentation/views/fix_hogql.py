import uuid
from typing import cast

import openai
import structlog
import posthoganalytics
from langchain_core.runnables import RunnableConfig
from posthoganalytics.ai.langchain.callbacks import CallbackHandler
from rest_framework import status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer, extend_schema
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.exceptions_capture import capture_exception
from posthog.models.user import User

logger = structlog.get_logger(__name__)

# Shown when the server has no usable LLM credentials, so a self-hosted admin knows it is a setup
# task on their side rather than a PostHog fault.
FIXER_NOT_CONFIGURED_MESSAGE = (
    "The AI query fixer isn't set up on this instance. It needs an LLM API key configured on the server."
)
# Shown when the fixer has credentials but the run failed (provider quota, timeout, network).
FIXER_FAILED_MESSAGE = "The AI query fixer couldn't run. Please try again in a moment."


def _is_missing_credentials_error(error: Exception) -> bool:
    if isinstance(error, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return True
    # A completely absent key raises a bare OpenAIError at client construction, before any request.
    return isinstance(error, openai.OpenAIError) and "api_key" in str(error).lower()


class FixHogQLViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    serializer_class = _FallbackSerializer

    @extend_schema(operation_id="fix_hogql_list")
    def list(self, request: Request, *args, **kwargs) -> Response:
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def create(self, request: Request, *args, **kwargs) -> Response:
        from products.data_warehouse.backend.facade.api import HogQLQueryFixerTool

        query = request.data.get("query", None)
        error = request.data.get("error", "")
        connection_id = request.data.get("connection_id", None)

        if query is None:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "No query provided"},
            )

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

        try:
            result = HogQLQueryFixerTool(
                team=self.team, user=user, config=config, tool_call_id="fix_hogql_query_tool_call_id"
            ).invoke({})
        except Exception as e:
            logger.exception("fix_hogql_query_failed", trace_id=trace_id, team_id=self.team.id)
            if _is_missing_credentials_error(e):
                # A self-hosted instance without LLM credentials is a setup task, not a fault, so it
                # stays out of error tracking. That suppression is the reason this case is handled here.
                message = FIXER_NOT_CONFIGURED_MESSAGE
            else:
                # Any other failure can be a genuine defect, for example a schema build error, a
                # database error, or a bug in the tool body. The Response returned below never enters
                # DRF's exception path, so report it here to keep it in error tracking.
                message = FIXER_FAILED_MESSAGE
                capture_exception(e, {"team_id": self.team.id, "user_id": user.id})
            return Response({"trace_id": trace_id, "error": message}, status=status.HTTP_400_BAD_REQUEST)

        if result is None or (isinstance(result, str) and len(result) == 0):
            return Response({"trace_id": trace_id, "error": "Could not fix the query"}, status=400)

        return Response({"query": result, "trace_id": trace_id}, status=200)
