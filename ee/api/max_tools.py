from typing import Any, cast
from uuid import uuid4

import pydantic
from asgiref.sync import async_to_sync
from drf_spectacular.utils import extend_schema
from pydantic import BaseModel
from rest_framework import serializers
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

from products.error_tracking.backend.tools.search_issues import SearchErrorTrackingIssuesTool

from ee.hogai.tool import MaxTool
from ee.hogai.tools import CreateInsightTool, ExecuteSQLTool, UpsertDashboardTool
from ee.hogai.tools.replay.filter_session_recordings import FilterSessionRecordingsTool
from ee.hogai.tools.replay.summarize_sessions import SummarizeSessionsTool
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import NodePath
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


MAX_TOOLS: dict[str, type[MaxTool]] = {
    "create_insight": CreateInsightTool,
    "execute_sql": ExecuteSQLTool,
    "filter_session_recordings": FilterSessionRecordingsTool,
    "search_error_tracking_issues": SearchErrorTrackingIssuesTool,
    "summarize_sessions": SummarizeSessionsTool,
    "upsert_dashboard": UpsertDashboardTool,
}


def _create_tool_action(tool_name: str, tool_class: type[MaxTool]):
    """Create an action method for a specific tool."""

    # Some tools define args_schema dynamically in create_tool_class, so check if it exists as class attr
    args_schema = getattr(tool_class, "args_schema", None)
    request_schema = args_schema if isinstance(args_schema, type) and issubclass(args_schema, BaseModel) else None

    @extend_schema(request=request_schema, tags=["MaxTools"])
    def tool_action(self, request: Request, **kwargs):
        # Create a conversation for this tool call so artifacts can be stored
        conversation = self.get_queryset().create(
            user=request.user,
            team=self.team,
            type=Conversation.Type.TOOL_CALL,
        )

        # Generate a unique tool_call_id for this invocation
        tool_call_id = str(uuid4())

        # Create a config with the conversation ID as thread_id
        config = {"configurable": {"thread_id": str(conversation.id)}}

        # Create a node_path with the tool_call_id (required by tools that generate messages)
        node_path = (NodePath(name=f"max_tools.{tool_name}", tool_call_id=tool_call_id),)

        # Create tool instance with config - some tools define args_schema dynamically
        tool = async_to_sync(tool_class.create_tool_class)(
            team=self.team,
            user=cast(User, request.user),
            config=config,
            node_path=node_path,
        )

        # Get schema from instance (may differ from class attr for dynamic tools)
        instance_schema = getattr(tool, "args_schema", None)
        if not instance_schema or not isinstance(instance_schema, type) or not issubclass(instance_schema, BaseModel):
            raise serializers.ValidationError(f"Tool '{tool_name}' has no valid args schema")

        try:
            validated_args = instance_schema.model_validate(request.data)
        except pydantic.ValidationError as e:
            raise serializers.ValidationError({"errors": e.errors()})

        # Extract field values directly from the Pydantic model (preserves nested Pydantic models)
        # Using model_dump() would convert nested models to dicts, breaking tools that expect Pydantic types
        args_dict = {field_name: getattr(validated_args, field_name) for field_name in validated_args.model_fields}
        result_content, result_artifact = async_to_sync(tool._arun_impl)(**args_dict)

        # Handle artifact serialization - some tools return Pydantic models, some return dicts
        if result_artifact is None:
            artifact_data = None
        elif isinstance(result_artifact, BaseModel):
            artifact_data = result_artifact.model_dump()
        else:
            artifact_data = result_artifact

        return Response(
            {
                "content": result_content,
                "artifact": artifact_data,
            }
        )

    tool_action.__name__ = f"invoke_{tool_name}"
    tool_action.__doc__ = tool_class.description if hasattr(tool_class, "description") else f"Invoke {tool_name} tool"

    return action(
        detail=False,
        methods=["POST"],
        url_path=f"{tool_name}",
        required_scopes=["query:read"],
    )(tool_action)


class MaxToolsViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    scope_object = "project"
    queryset = Conversation.objects.all()

    permission_classes = [IsAuthenticated]
    renderer_classes = [SafeJSONRenderer]
    throttle_classes = [AIBurstRateThrottle, AISustainedRateThrottle]
    authentication_classes = [PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]

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


# Dynamically add tool actions to the viewset
for _tool_name, _tool_class in MAX_TOOLS.items():
    setattr(MaxToolsViewSet, f"invoke_{_tool_name}", _create_tool_action(_tool_name, _tool_class))
