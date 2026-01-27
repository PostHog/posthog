import time
import uuid
from collections.abc import AsyncGenerator
from typing import cast

from django.conf import settings
from django.http import StreamingHttpResponse

import pydantic
import structlog
from asgiref.sync import async_to_sync as asgi_async_to_sync
from drf_spectacular.utils import extend_schema
from loginas.utils import is_impersonated_session
from prometheus_client import Histogram
from rest_framework import exceptions, serializers, status
from rest_framework.decorators import action
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.schema import AgentMode, AssistantMessage, HumanMessage, MaxBillingContext

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.exceptions import Conflict, QuotaLimitExceeded
from posthog.exceptions_capture import capture_exception
from posthog.models.user import User
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle
from posthog.temporal.ai.chat_agent import (
    CHAT_AGENT_STREAM_MAX_LENGTH,
    CHAT_AGENT_WORKFLOW_TIMEOUT,
    ChatAgentWorkflow,
    ChatAgentWorkflowInputs,
)

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited
from ee.hogai.api.serializers import ConversationSerializer
from ee.hogai.chat_agent import AssistantGraph
from ee.hogai.core.executor import AgentExecutor
from ee.hogai.stream.redis_stream import get_conversation_stream_key
from ee.hogai.utils.aio import async_to_sync
from ee.hogai.utils.sse import AssistantSSESerializer
from ee.hogai.utils.types import PartialAssistantState
from ee.models.assistant import Conversation

logger = structlog.get_logger(__name__)

STREAM_ITERATION_LATENCY_HISTOGRAM = Histogram(
    "posthog_ai_stream_iteration_latency_seconds",
    "Time between iterations in the async stream loop",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf")],
)


class MessageMinimalSerializer(serializers.Serializer):
    """Serializer for appending a message to an existing conversation without triggering AI processing."""

    content = serializers.CharField(required=True, max_length=10000)


class MessageSerializer(MessageMinimalSerializer):
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
    agent_mode = serializers.ChoiceField(required=False, choices=[mode.value for mode in AgentMode])
    resume_payload = serializers.JSONField(required=False, allow_null=True)

    def validate(self, data):
        if data["content"] is not None:
            try:
                message = HumanMessage.model_validate(
                    {
                        "content": data["content"],
                        "ui_context": data.get("ui_context"),
                        "trace_id": str(data["trace_id"]) if data.get("trace_id") else None,
                    }
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
        if agent_mode := data.get("agent_mode"):
            try:
                data["agent_mode"] = AgentMode(agent_mode)
            except ValueError:
                raise serializers.ValidationError("Invalid agent mode.")
        return data


@extend_schema(tags=["max"])
class ConversationViewSet(TeamAndOrgViewSetMixin, ListModelMixin, RetrieveModelMixin, GenericViewSet):
    scope_object = "conversation"
    serializer_class = ConversationSerializer
    queryset = Conversation.objects.all()
    lookup_url_kwarg = "conversation"

    def safely_get_queryset(self, queryset):
        # Only single retrieval of a specific conversation is allowed for other users' conversations (if ID known)
        if self.action != "retrieve":
            queryset = queryset.filter(user=self.request.user)
        # For listing or single retrieval, conversations must be from the assistant and have a title
        if self.action in ("list", "retrieve"):
            queryset = queryset.filter(
                title__isnull=False,
                type__in=[Conversation.Type.DEEP_RESEARCH, Conversation.Type.ASSISTANT, Conversation.Type.SLACK],
            )
            # Hide internal conversations from customers, but show them to support agents during impersonation
            if not is_impersonated_session(self.request):
                queryset = queryset.filter(is_internal=False)
            queryset = queryset.order_by("-updated_at")
        return queryset

    def get_throttles(self):
        if (
            # Do not apply limits in local development
            not settings.DEBUG
            # Only for streaming
            and self.action == "create"
            # No limits for customers
            and not self.organization.customer_id
        ):
            return [AIBurstRateThrottle(), AISustainedRateThrottle()]

        return super().get_throttles()

    def get_serializer_class(self):
        if self.action == "create":
            return MessageSerializer
        if self.action == "append_message":
            return MessageMinimalSerializer
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

        if is_team_limited(self.team.api_token, QuotaResource.AI_CREDITS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY):
            raise QuotaLimitExceeded(
                "Your organization reached its AI credit usage limit. Increase the limits in Billing settings, or ask an org admin to do so."
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversation_id = serializer.validated_data["conversation"]

        has_message = serializer.validated_data.get("content") is not None
        is_deep_research = serializer.validated_data.get("deep_research_mode", False)
        if is_deep_research:
            raise NotImplementedError("Deep research is not supported yet")

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
            # Mark conversation as internal if created during an impersonated session (support agents)
            is_impersonated = is_impersonated_session(request)
            conversation_type = Conversation.Type.DEEP_RESEARCH if is_deep_research else Conversation.Type.ASSISTANT
            conversation = Conversation.objects.create(
                user=cast(User, request.user),
                team=self.team,
                id=conversation_id,
                type=conversation_type,
                is_internal=is_impersonated,
            )
            is_new_conversation = True

        is_idle = conversation.status == Conversation.Status.IDLE
        has_message = serializer.validated_data.get("message") is not None
        has_resume_payload = serializer.validated_data.get("resume_payload") is not None

        if has_message and not is_idle:
            raise Conflict("Cannot resume streaming with a new message")
        # If the frontend is trying to resume streaming for a finished conversation, return a conflict error
        if not has_message and conversation.status == Conversation.Status.IDLE and not has_resume_payload:
            raise exceptions.ValidationError("Cannot continue streaming from an idle conversation")

        # Skip billing for impersonated sessions (support agents) and mark conversations as internal
        is_impersonated = is_impersonated_session(request)
        is_agent_billable = not is_impersonated
        workflow_inputs = ChatAgentWorkflowInputs(
            team_id=self.team_id,
            user_id=cast(User, request.user).pk,  # Use pk instead of id for User model
            conversation_id=conversation.id,
            stream_key=get_conversation_stream_key(conversation.id),
            message=serializer.validated_data["message"].model_dump() if has_message else None,
            contextual_tools=serializer.validated_data.get("contextual_tools"),
            is_new_conversation=is_new_conversation,
            trace_id=serializer.validated_data["trace_id"],
            session_id=request.headers.get("X-POSTHOG-SESSION-ID"),  # Relies on posthog-js __add_tracing_headers
            billing_context=serializer.validated_data.get("billing_context"),
            agent_mode=serializer.validated_data.get("agent_mode"),
            use_checkpointer=True,
            is_agent_billable=is_agent_billable,
            resume_payload=serializer.validated_data.get("resume_payload"),
        )
        workflow_class = ChatAgentWorkflow

        async def async_stream(
            workflow_inputs: ChatAgentWorkflowInputs,
        ) -> AsyncGenerator[bytes, None]:
            serializer = AssistantSSESerializer()
            stream_manager = AgentExecutor(
                conversation, timeout=CHAT_AGENT_WORKFLOW_TIMEOUT, max_length=CHAT_AGENT_STREAM_MAX_LENGTH
            )
            last_iteration_time = time.time()
            async for chunk in stream_manager.astream(workflow_class, workflow_inputs):
                chunk_received_time = time.time()
                STREAM_ITERATION_LATENCY_HISTOGRAM.observe(chunk_received_time - last_iteration_time)
                last_iteration_time = chunk_received_time

                event = await serializer.dumps(chunk)
                yield event.encode("utf-8")

        return StreamingHttpResponse(
            (
                async_stream(workflow_inputs)
                if settings.SERVER_GATEWAY_INTERFACE == "ASGI"
                else async_to_sync(lambda: async_stream(workflow_inputs))
            ),
            content_type="text/event-stream",
        )

    @action(detail=True, methods=["PATCH"])
    def cancel(self, request: Request, *args, **kwargs):
        conversation = self.get_object()

        if conversation.status in [Conversation.Status.CANCELING, Conversation.Status.IDLE]:
            return Response(status=status.HTTP_204_NO_CONTENT)

        async def cancel_workflow():
            agent_executor = AgentExecutor(conversation)
            await agent_executor.cancel_workflow()

        try:
            asgi_async_to_sync(cancel_workflow)()
        except Exception as e:
            logger.exception("Failed to cancel conversation", conversation_id=conversation.id, error=str(e))
            return Response({"error": "Failed to cancel conversation"}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["POST"], url_path="append_message")
    def append_message(self, request: Request, *args, **kwargs):
        """
        Appends a message to an existing conversation without triggering AI processing.
        This is used for client-side generated messages that need to be persisted
        (e.g., support ticket confirmation messages).
        """
        conversation = self.get_object()

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        content = serializer.validated_data["content"]
        message = AssistantMessage(content=content, id=str(uuid.uuid4()))

        async def append_to_state():
            user = cast(User, request.user)
            graph = AssistantGraph(self.team, user).compile_full_graph()
            # Empty checkpoint_ns targets the root graph (not subgraphs)
            config = {"configurable": {"thread_id": str(conversation.id), "checkpoint_ns": ""}}
            await graph.aupdate_state(
                config,
                PartialAssistantState(messages=[message]),
            )

        try:
            asgi_async_to_sync(append_to_state)()
        except Exception as e:
            logger.exception("Failed to append message to conversation", conversation_id=conversation.id, error=str(e))
            return Response({"error": "Failed to append message"}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        return Response({"id": message.id}, status=status.HTTP_201_CREATED)
