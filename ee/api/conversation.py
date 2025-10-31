from collections.abc import AsyncGenerator
from typing import cast

from django.conf import settings
from django.http import StreamingHttpResponse

import pydantic
import structlog
from asgiref.sync import async_to_sync as asgi_async_to_sync
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.schema import HumanMessage, MaxBillingContext

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.exceptions import Conflict
from posthog.exceptions_capture import capture_exception
from posthog.models.user import User
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle
from posthog.temporal.ai.conversation import AssistantConversationRunnerWorkflowInputs
from posthog.utils import get_instance_region

from ee.hogai.api.serializers import ConversationSerializer
from ee.hogai.utils.aio import async_to_sync
from ee.hogai.utils.assistant_executor import AssistantExecutor
from ee.hogai.utils.sse import AssistantSSESerializer
from ee.hogai.utils.types.base import AssistantMode
from ee.models.assistant import Conversation

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
    billing_context = serializers.JSONField(required=False)
    trace_id = serializers.UUIDField(required=True)
    session_id = serializers.CharField(required=False)
    deep_research_mode = serializers.BooleanField(required=False, default=False)

    def validate(self, data):
        if data["content"] is not None:
            try:
                message = HumanMessage.model_validate(
                    {"content": data["content"], "ui_context": data.get("ui_context")}
                )
            except pydantic.ValidationError:
                if settings.DEBUG:
                    raise
                raise serializers.ValidationError("Invalid message content.")
            data["message"] = message
        else:
            # NOTE: If content is empty, it means we're resuming streaming or continuing generation with only the contextual_tools potentially different
            # Because we intentionally don't add a HumanMessage, we are NOT updating ui_context here
            data["message"] = None
        billing_context = data.get("billing_context")
        if billing_context:
            try:
                billing_context = MaxBillingContext.model_validate(billing_context)
                data["billing_context"] = billing_context
            except pydantic.ValidationError as e:
                capture_exception(e)
                # billing data relies on a lot of legacy code, this might break and we don't want to block the conversation
                data["billing_context"] = None
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
        return qs.filter(
            title__isnull=False, type__in=[Conversation.Type.DEEP_RESEARCH, Conversation.Type.ASSISTANT]
        ).order_by("-updated_at")

    def get_throttles(self):
        if (
            # Do not apply limits in local development
            not settings.DEBUG
            # Only for streaming
            and self.action == "create"
            # Strict limits are skipped for select US region teams (PostHog + an active user we've chatted with)
            and not (get_instance_region() == "US" and self.team_id in (2, 87921, 41124))
        ):
            return [AIBurstRateThrottle(), AISustainedRateThrottle()]

        return super().get_throttles()

    def get_serializer_class(self):
        if self.action == "create":
            return MessageSerializer
        return super().get_serializer_class()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["team"] = self.team
        context["user"] = cast(User, self.request.user)
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
        is_deep_research = serializer.validated_data.get("deep_research_mode", False)
        mode = AssistantMode.DEEP_RESEARCH if is_deep_research else AssistantMode.ASSISTANT

        is_new_conversation = False
        # Safely set the lookup kwarg for potential error handling
        if self.lookup_url_kwarg:
            self.kwargs[self.lookup_url_kwarg] = conversation_id
        try:
            conversation = Conversation.objects.get(id=conversation_id)
            if conversation.user != request.user or conversation.team != self.team:
                return Response(
                    {"error": "Cannot access other users' conversations"}, status=status.HTTP_400_BAD_REQUEST
                )
        except Conversation.DoesNotExist:
            # Conversation doesn't exist, create it if we have a message
            if not has_message:
                return Response(
                    {"error": "Cannot stream from non-existent conversation"}, status=status.HTTP_400_BAD_REQUEST
                )
            # Use frontend-provided conversation ID
            conversation_type = Conversation.Type.DEEP_RESEARCH if is_deep_research else Conversation.Type.ASSISTANT
            conversation = Conversation.objects.create(
                user=cast(User, request.user), team=self.team, id=conversation_id, type=conversation_type
            )
            is_new_conversation = True

        is_idle = conversation.status == Conversation.Status.IDLE
        has_message = serializer.validated_data.get("message") is not None

        if has_message and not is_idle:
            raise Conflict("Cannot resume streaming with a new message")

        workflow_inputs = AssistantConversationRunnerWorkflowInputs(
            team_id=self.team_id,
            user_id=cast(User, request.user).pk,  # Use pk instead of id for User model
            conversation_id=conversation.id,
            message=serializer.validated_data["message"].model_dump() if has_message else None,
            contextual_tools=serializer.validated_data.get("contextual_tools"),
            is_new_conversation=is_new_conversation,
            trace_id=serializer.validated_data["trace_id"],
            session_id=request.headers.get("X-POSTHOG-SESSION-ID"),  # Relies on posthog-js __add_tracing_headers
            billing_context=serializer.validated_data.get("billing_context"),
            mode=mode,
        )

        async def async_stream(
            workflow_inputs: AssistantConversationRunnerWorkflowInputs,
        ) -> AsyncGenerator[bytes, None]:
            serializer = AssistantSSESerializer()
            stream_manager = AssistantExecutor(conversation)
            async for chunk in stream_manager.astream(workflow_inputs):
                yield serializer.dumps(chunk).encode("utf-8")

        return StreamingHttpResponse(
            async_stream(workflow_inputs)
            if settings.SERVER_GATEWAY_INTERFACE == "ASGI"
            else async_to_sync(lambda: async_stream(workflow_inputs)),
            content_type="text/event-stream",
        )

    @action(detail=True, methods=["PATCH"])
    def cancel(self, request: Request, *args, **kwargs):
        conversation = self.get_object()

        if conversation.status in [Conversation.Status.CANCELING, Conversation.Status.IDLE]:
            return Response(status=status.HTTP_204_NO_CONTENT)

        async def cancel_workflow():
            conversation_manager = AssistantExecutor(conversation)
            await conversation_manager.cancel_conversation()

        try:
            asgi_async_to_sync(cancel_workflow)()
        except Exception as e:
            logger.exception("Failed to cancel conversation", conversation_id=conversation.id, error=str(e))
            return Response({"error": "Failed to cancel conversation"}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        return Response(status=status.HTTP_204_NO_CONTENT)
