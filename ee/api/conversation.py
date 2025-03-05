from typing import cast

import pydantic
from django.http import StreamingHttpResponse
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.renderers import BaseRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from ee.hogai.assistant import Assistant
from ee.models.assistant import Conversation
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.exceptions import Conflict
from posthog.models.user import User
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle
from posthog.schema import HumanMessage


class MessageSerializer(serializers.Serializer):
    content = serializers.CharField(required=True, max_length=1000)
    conversation = serializers.UUIDField(required=False)
    trace_id = serializers.UUIDField(required=True)

    def validate(self, data):
        try:
            message = HumanMessage(content=data["content"])
            data["message"] = message
        except pydantic.ValidationError:
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
    queryset = Conversation.objects.all()
    lookup_url_kwarg = "conversation"

    def safely_get_queryset(self, queryset):
        # Only allow access to conversations created by the current user
        return queryset.filter(user=self.request.user)

    def get_throttles(self):
        return [AIBurstRateThrottle(), AISustainedRateThrottle()]

    def get_renderers(self):
        if self.action == "create":
            return [ServerSentEventRenderer()]
        return super().get_renderers()

    def create(self, request: Request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversation_id = serializer.validated_data.get("conversation")
        if conversation_id:
            self.kwargs[self.lookup_url_kwarg] = conversation_id
            conversation = self.get_object()
        else:
            conversation = self.get_queryset().create(user=request.user, team=self.team)
        if conversation.is_locked:
            raise Conflict("Conversation is locked.")
        assistant = Assistant(
            self.team,
            conversation,
            serializer.validated_data["message"],
            user=cast(User, request.user),
            is_new_conversation=not conversation_id,
            trace_id=serializer.validated_data["trace_id"],
        )
        return StreamingHttpResponse(assistant.stream(), content_type=ServerSentEventRenderer.media_type)

    @action(detail=True, methods=["PATCH"])
    def cancel(self, request: Request, *args, **kwargs):
        conversation = self.get_object()
        if conversation.status == Conversation.Status.CANCELING:
            raise ValidationError("Generation has already been cancelled.")
        conversation.status = Conversation.Status.CANCELING
        conversation.save()
        return Response(status=status.HTTP_204_NO_CONTENT)
