from typing import Any, cast
from uuid import uuid4

import pydantic
from asgiref.sync import async_to_sync
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.models.user import User
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle
from posthog.renderers import SafeJSONRenderer

from ee.hogai.external_tool import mcp_tool_registry
from ee.hogai.tool_errors import MaxToolError
from ee.hogai.utils.types import AssistantState
from ee.models.assistant import Conversation


class InsightsToolCallSerializer(serializers.Serializer):
    query = serializers.CharField(required=True, max_length=1000)
    insight_type = serializers.ChoiceField(choices=["trends", "funnel", "retention", "sql"])

    def validate(self, data: dict[str, Any]):
        try:
            tool_call_state = AssistantState(
                root_tool_call_id=str(uuid4()),
                root_tool_insight_plan=data["query"],
                root_tool_insight_type=data["insight_type"],
                messages=[],
            )
            data["state"] = tool_call_state
        except pydantic.ValidationError:
            raise serializers.ValidationError("Invalid state content.")
        return data


class MaxToolsViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    scope_object = "project"
    queryset = Conversation.objects.all()

    permission_classes = [IsAuthenticated]
    renderer_classes = [SafeJSONRenderer]
    throttle_classes = [AIBurstRateThrottle, AISustainedRateThrottle]
    authentication_classes = [PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]

    def dangerously_get_required_scopes(self, request, view) -> list[str] | None:
        if self.action == "invoke_tool":
            import ee.hogai.tools  # noqa: F401

            tool_name = self.kwargs.get("tool_name", "")
            scopes = mcp_tool_registry.get_scopes(tool_name)
            return scopes or None
        return None

    @action(
        detail=False,
        methods=["POST"],
        url_path="create_and_query_insight",
        required_scopes=["insight:read", "query:read"],
    )
    def create_and_query_insight(self, request: Request, *args, **kwargs):
        from ee.hogai.insights_assistant import InsightsAssistant

        serializer = InsightsToolCallSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversation = self.get_queryset().create(user=request.user, team=self.team, type=Conversation.Type.TOOL_CALL)
        assistant = InsightsAssistant(
            self.team,
            conversation,
            user=cast(User, request.user),
            is_new_conversation=False,  # we don't care about the conversation id being sent back to the client
            initial_state=serializer.validated_data["state"],
        )

        return Response(
            [
                {"type": event_type, "data": data.model_dump(exclude_none=True)}
                for event_type, data in assistant.invoke()
            ]
        )

    @action(
        detail=False,
        methods=["POST"],
        url_path="invoke/(?P<tool_name>[^/.]+)",
    )
    def invoke_tool(self, request: Request, tool_name: str, *args, **kwargs):
        """
        Invoke an MCP tool by name.

        This endpoint allows MCP callers to invoke Max AI tools directly
        without going through the full LangChain conversation flow.

        Scopes are resolved dynamically per tool via dangerously_get_required_scopes.
        """
        import ee.hogai.tools  # noqa: F401

        tool = mcp_tool_registry.get(tool_name, team=self.team, user=cast(User, request.user))
        if tool is None:
            return Response(
                {"content": f"Tool '{tool_name}' not found", "isError": True},
                status=status.HTTP_404_NOT_FOUND,
            )

        args_data = request.data.get("args", {})

        try:
            validated_args = tool.args_schema.model_validate(args_data)
        except pydantic.ValidationError as e:
            return Response(
                {"content": f"There was a validation error calling the tool: {e}", "isError": True},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            content, data = async_to_sync(tool.execute)(validated_args)
        except MaxToolError as e:
            return Response({"content": f"Tool failed: {e.to_summary()}.{e.retry_hint}", "isError": True})
        except Exception:
            return Response(
                {
                    "content": "The tool raised an internal error. Do not immediately retry the tool call.",
                    "isError": True,
                }
            )

        response_data: dict[str, Any] = {"content": content}
        if data is not None:
            response_data["data"] = data
        return Response(response_data)
