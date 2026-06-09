import json
from typing import Any, cast
from uuid import uuid4

import pydantic
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
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

from products.messaging.backend.api.message_templates import MessageTemplateSerializer
from products.posthog_ai.backend.models.assistant import Conversation

from ee.hogai.chat_agent.schema_generator.parsers import PydanticOutputParserException
from ee.hogai.utils.types import AssistantState


class CreateMessageTemplateToolSerializer(serializers.Serializer):
    instructions = serializers.CharField(
        required=True,
        max_length=4000,
        help_text="What email template to generate. May include a single URL to draw branding and copy from.",
    )
    name = serializers.CharField(
        required=False,
        max_length=400,
        help_text="Optional template name. Falls back to a name generated from the instructions.",
    )
    message_category = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Optional message category ID to file the template under.",
    )


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

    @extend_schema(request=InsightsToolCallSerializer, responses={200: OpenApiTypes.OBJECT})
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
            is_agent_billable=False,
        )

        return Response(
            [
                {"type": event_type, "data": data.model_dump(exclude_none=True)}
                for event_type, data in assistant.invoke()
            ]
        )

    @extend_schema(request=CreateMessageTemplateToolSerializer, responses={200: MessageTemplateSerializer})
    @action(
        detail=False,
        methods=["POST"],
        url_path="create_message_template",
        required_scopes=["hog_flow:write"],
    )
    def create_message_template(self, request: Request, *args, **kwargs):
        # Inline to keep the heavy ee.hogai import chain off this module's import path.
        from products.workflows.backend.max_tools import CreateMessageTemplateTool

        serializer = CreateMessageTemplateToolSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tool = CreateMessageTemplateTool(team=self.team, user=cast(User, request.user))
        try:
            _content, template_json = tool._run_impl(instructions=serializer.validated_data["instructions"])
            generated = json.loads(template_json)
        except (PydanticOutputParserException, json.JSONDecodeError):
            raise serializers.ValidationError(
                {
                    "instructions": "Could not generate a valid email template. Add detail about the email's purpose, "
                    "audience, and branding, then try again."
                }
            )

        template_data: dict[str, Any] = {
            "name": serializer.validated_data.get("name") or generated.get("name") or "Untitled template",
            "description": generated.get("description") or "",
            "content": generated["content"],
            "type": "email",
        }
        if serializer.validated_data.get("message_category"):
            template_data["message_category"] = serializer.validated_data["message_category"]

        context = {"request": request, "team_id": self.team_id}
        template_serializer = MessageTemplateSerializer(data=template_data, context=context)
        template_serializer.is_valid(raise_exception=True)
        instance = template_serializer.save()

        return Response(MessageTemplateSerializer(instance, context=context).data)
