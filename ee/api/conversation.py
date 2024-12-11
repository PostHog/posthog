from typing import Any, cast

from django.http import StreamingHttpResponse
from pydantic import ValidationError
from rest_framework import serializers
from rest_framework.renderers import BaseRenderer
from rest_framework.request import Request
from rest_framework.viewsets import GenericViewSet

from ee.hogai.assistant import Assistant
from ee.models.assistant import Conversation
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle
from posthog.schema import RootAssistantMessage


class ConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = ["id", "message"]
        extra_kwargs = {
            "id": {"required": False},
        }

    message = serializers.DictField(required=True)

    def validate_message(self, value: Any):
        try:
            return RootAssistantMessage.model_validate(value)
        except ValidationError as e:
            raise serializers.ValidationError(str(e))


class ServerSentEventRenderer(BaseRenderer):
    media_type = "text/event-stream"
    format = "txt"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data


class ConversationViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    scope_object = "conversation"
    serializer_class = ConversationSerializer
    renderer_classes = [ServerSentEventRenderer]

    def safely_get_queryset(self, queryset):
        # Only allow access to conversations created by the current user
        return Conversation.objects.filter(user=self.request.user)

    def get_throttles(self):
        return [AIBurstRateThrottle(), AISustainedRateThrottle()]

    def create(self, request: Request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        conversation = None
        if data.get("id"):
            conversation = self.get_object()
            created = False
        if not conversation:
            conversation = self.get_queryset().create(user=request.user, team=self.team)
            created = True
        assistant = Assistant(
            self.team, conversation, data["message"], user=cast(User, request.user), send_conversation=created
        )
        return StreamingHttpResponse(assistant.stream(), content_type=ServerSentEventRenderer.media_type)
