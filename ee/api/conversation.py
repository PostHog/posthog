from typing import cast

import pydantic
from django.http import StreamingHttpResponse
from langgraph.graph.state import CompiledStateGraph
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from ee.hogai.assistant import Assistant
from ee.hogai.graph.graph import AssistantGraph
from ee.hogai.utils.types import AssistantMode, AssistantState
from ee.models.assistant import Conversation
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.exceptions import Conflict
from posthog.models.user import User
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle
from posthog.renderers import ServerSentEventRenderer
from posthog.schema import HumanMessage


class MessageSerializer(serializers.Serializer):
    content = serializers.CharField(required=True, max_length=1000)
    conversation = serializers.UUIDField(required=False)
    contextual_tools = serializers.DictField(required=False, child=serializers.JSONField())
    trace_id = serializers.UUIDField(required=True)

    def validate(self, data):
        try:
            message = HumanMessage(content=data["content"])
            data["message"] = message
        except pydantic.ValidationError:
            raise serializers.ValidationError("Invalid message content.")
        return data


class ConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = ["id", "status", "title", "messages"]
        read_only_fields = fields

    messages = serializers.SerializerMethodField()

    def get_messages(self, conversation: Conversation):
        graph: CompiledStateGraph = self.context["assistant_graph"]
        snapshot = graph.get_state({"configurable": {"thread_id": str(conversation.id)}})
        try:
            state = AssistantState.model_validate(snapshot.values)
            return state.model_dump()["messages"]
        except (pydantic.ValidationError, KeyError):
            return []


class ConversationViewSet(TeamAndOrgViewSetMixin, ListModelMixin, RetrieveModelMixin, GenericViewSet):
    scope_object = "INTERNAL"
    serializer_class = ConversationSerializer
    queryset = Conversation.objects.all()
    lookup_url_kwarg = "conversation"

    def safely_get_queryset(self, queryset):
        # Only allow access to conversations created by the current user
        qs = queryset.filter(user=self.request.user)

        # Allow sending messages to any conversation
        if self.action == "create":
            return qs

        # But retrieval must only return conversations from the assistant and with a title.
        return qs.filter(title__isnull=False, type=Conversation.Type.ASSISTANT)

    def get_throttles(self):
        if self.action == "create":
            return [AIBurstRateThrottle(), AISustainedRateThrottle()]
        return super().get_throttles()

    def get_renderers(self):
        if self.action == "create":
            return [ServerSentEventRenderer()]
        return super().get_renderers()

    def get_serializer_class(self):
        if self.action == "create":
            return MessageSerializer
        return super().get_serializer_class()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["assistant_graph"] = AssistantGraph(self.team).compile_full_graph()
        return context

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
            new_message=serializer.validated_data["message"],
            user=cast(User, request.user),
            contextual_tools=serializer.validated_data.get("contextual_tools"),
            is_new_conversation=not conversation_id,
            trace_id=serializer.validated_data["trace_id"],
            mode=AssistantMode.ASSISTANT,
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
