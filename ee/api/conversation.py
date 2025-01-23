from typing import cast

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
from posthog.schema import HumanMessage


class MessageSerializer(serializers.Serializer):
    content = serializers.CharField(required=True, max_length=1000)
    conversation = serializers.UUIDField(required=False)

    def validate(self, data):
        try:
            message = HumanMessage(content=data["content"])
            data["message"] = message
        except ValidationError:
            raise serializers.ValidationError("Invalid message content.")
        return data


class ServerSentEventRenderer(BaseRenderer):
    media_type = "text/event-stream"
    format = "txt"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data


class ConversationViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    scope_object = "INTERNAL"
    serializer_class = MessageSerializer
    renderer_classes = [ServerSentEventRenderer]
    queryset = Conversation.objects.all()
    lookup_url_kwarg = "conversation"

    def safely_get_queryset(self, queryset):
        # Only allow access to conversations created by the current user
        return queryset.filter(user=self.request.user)

    def get_throttles(self):
        return [AIBurstRateThrottle(), AISustainedRateThrottle()]

    def create(self, request: Request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversation_id = serializer.validated_data.get("conversation")
        if conversation_id:
            self.kwargs[self.lookup_url_kwarg] = conversation_id
            conversation = self.get_object()
        else:
            conversation = self.get_queryset().create(user=request.user, team=self.team)
        assistant = Assistant(
            self.team,
            conversation,
            serializer.validated_data["message"],
            user=cast(User, request.user),
            is_new_conversation=not conversation_id,
        )
        return StreamingHttpResponse(assistant.stream(), content_type=ServerSentEventRenderer.media_type)
