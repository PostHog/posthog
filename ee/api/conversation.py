import pydantic
import structlog
from django.conf import settings
from django.http import Http404, StreamingHttpResponse
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from typing import cast

from ee.hogai.api.serializers import ConversationSerializer
from ee.hogai.stream.conversation_stream import ConversationStreamManager
from ee.hogai.graph.graph import AssistantGraph
from ee.hogai.utils.aio import async_to_sync
from asgiref.sync import async_to_sync as asgi_async_to_sync
from ee.hogai.utils.sse import AssistantSSESerializer
from ee.hogai.utils.types import AssistantMode
from ee.models.assistant import Conversation
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle
from posthog.schema import HumanMessage
from posthog.temporal.ai.conversation import AssistantConversationRunnerWorkflowInputs
from posthog.utils import get_instance_region

logger = structlog.get_logger(__name__)


class MessageSerializer(serializers.Serializer):
    content = serializers.CharField(
        required=True,
        allow_null=True,  # Null content means we're continuing previous generation or resuming streaming
        max_length=40000,  # Roughly 10k tokens
    )
    conversation = serializers.UUIDField(
        required=True
    )  # this either retrieves an existing conversation or creates a new one
    contextual_tools = serializers.DictField(required=False, child=serializers.JSONField())
    ui_context = serializers.JSONField(required=False)
    trace_id = serializers.UUIDField(required=True)

    def validate(self, data):
        if data["content"] is not None:
            try:
                message = HumanMessage.model_validate(
                    {"content": data["content"], "ui_context": data.get("ui_context")}
                )
            except pydantic.ValidationError:
                raise serializers.ValidationError("Invalid message content.")
            data["message"] = message
        else:
            # NOTE: If content is empty, it means we're resuming streaming or continuing generation with only the contextual_tools potentially different
            # Because we intentionally don't add a HumanMessage, we are NOT updating ui_context here
            data["message"] = None
        return data


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
        return qs.filter(title__isnull=False, type=Conversation.Type.ASSISTANT).order_by("-updated_at")

    def get_throttles(self):
        if (
            # Do not apply limits in local development
            not settings.DEBUG
            # Only for streaming
            and self.action == "create"
            # Strict limits are skipped for select US region teams (PostHog + an active user we've chatted with)
            and not (get_instance_region() == "US" and self.team_id in (2, 87921))
        ):
            return [AIBurstRateThrottle(), AISustainedRateThrottle()]

        return super().get_throttles()

    def get_serializer_class(self):
        if self.action == "create":
            return MessageSerializer
        return super().get_serializer_class()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["assistant_graph"] = AssistantGraph(self.team, cast(User, self.request.user)).compile_full_graph()
        return context

    def create(self, request: Request, *args, **kwargs):
        """
        Unified endpoint that handles both conversation creation and streaming.

        - If message is provided: Start new conversation processing
        - If no message: Stream from existing conversation
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversation_id = serializer.validated_data["conversation"]

        has_message = serializer.validated_data.get("content") is not None

        is_new_conversation = False
        self.kwargs[self.lookup_url_kwarg] = conversation_id
        try:
            conversation = self.get_object()
        except Http404:
            # Conversation doesn't exist, create it if we have a message
            if not has_message:
                return Response(
                    {"error": "Cannot stream from non-existent conversation"}, status=status.HTTP_400_BAD_REQUEST
                )
            # Use frontend-provided conversation ID
            conversation = Conversation.objects.create(
                user=cast(User, request.user), team=self.team, id=conversation_id
            )
            is_new_conversation = True

        is_idle = conversation.status == Conversation.Status.IDLE

        def get_stream_response(stream_func):
            async def async_stream():
                serializer = AssistantSSESerializer()
                stream_manager = ConversationStreamManager(conversation)
                async for chunk in stream_func(stream_manager):
                    yield serializer.dumps(chunk).encode("utf-8")

            if settings.SERVER_GATEWAY_INTERFACE == "ASGI":
                return async_stream()
            return async_to_sync(async_stream)

        # If this is a streaming request
        if not has_message and not is_idle:
            return StreamingHttpResponse(
                get_stream_response(lambda sm: sm.stream_conversation()), content_type="text/event-stream"
            )

        workflow_inputs = AssistantConversationRunnerWorkflowInputs(
            team_id=self.team_id,
            user_id=cast(User, request.user).id,
            conversation_id=conversation.id,
            message=serializer.validated_data["message"].model_dump() if serializer.validated_data["message"] else None,
            contextual_tools=serializer.validated_data.get("contextual_tools"),
            is_new_conversation=is_new_conversation,
            trace_id=str(serializer.validated_data["trace_id"]),
            mode=AssistantMode.ASSISTANT,
        )

        # Otherwise, process the new message (new generation) or resume generation
        return StreamingHttpResponse(
            get_stream_response(lambda sm: sm.start_workflow_and_stream(workflow_inputs)),
            content_type="text/event-stream",
        )

    @action(detail=True, methods=["PATCH"])
    def cancel(self, request: Request, *args, **kwargs):
        conversation = self.get_object()

        if conversation.status in [Conversation.Status.CANCELING, Conversation.Status.IDLE]:
            return Response(status=status.HTTP_204_NO_CONTENT)

        conversation.status = Conversation.Status.CANCELING
        conversation.save()

        async def cancel_workflow():
            conversation_manager = ConversationStreamManager(conversation)
            await conversation_manager.cancel_conversation()

        asgi_async_to_sync(cancel_workflow)()

        return Response(status=status.HTTP_204_NO_CONTENT)
