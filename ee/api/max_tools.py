from typing import Any, cast
from uuid import uuid4

import pydantic
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.models.user import User
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle
from posthog.renderers import SafeJSONRenderer

from ee.hogai.utils.types import AssistantMode, AssistantState
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
    authentication_classes = [PersonalAPIKeyAuthentication]

    @action(
        detail=False,
        methods=["POST"],
        url_path="create_and_query_insight",
        required_scopes=["insight:read", "query:read"],
    )
    def create_and_query_insight(self, request: Request, *args, **kwargs):
        from ee.hogai.assistant import Assistant

        serializer = InsightsToolCallSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversation = self.get_queryset().create(user=request.user, team=self.team, type=Conversation.Type.TOOL_CALL)
        assistant = Assistant.create(
            self.team,
            conversation,
            user=cast(User, request.user),
            is_new_conversation=False,  # we don't care about the conversation id being sent back to the client
            mode=AssistantMode.INSIGHTS_TOOL,
            initial_state=serializer.validated_data["state"],
        )

        return Response(
            [
                {"type": event_type, "data": data.model_dump(exclude_none=True)}
                for event_type, data in assistant.invoke()
            ]
        )
