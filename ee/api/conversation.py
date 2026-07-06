import time
import uuid
import asyncio
from collections.abc import AsyncGenerator, Iterable
from typing import cast

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

import pydantic
import structlog
from asgiref.sync import async_to_sync as asgi_async_to_sync
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from loginas.utils import is_impersonated_session
from prometheus_client import Histogram
from rest_framework import exceptions, serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import Throttled
from rest_framework.mixins import DestroyModelMixin, ListModelMixin, RetrieveModelMixin
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.schema import AgentMode, AssistantMessage, HumanMessage, MaxBillingContext

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.streaming import sse_streaming_response
from posthog.event_usage import report_user_action
from posthog.exceptions import Conflict, QuotaLimitExceeded
from posthog.exceptions_capture import capture_exception
from posthog.models.user import User
from posthog.rate_limit import (
    AIBurstRateThrottle,
    AIResearchBurstRateThrottle,
    AIResearchSustainedRateThrottle,
    AISustainedRateThrottle,
    is_team_exempt_from_ai_rate_limit,
)
from posthog.temporal.ai.chat_agent import (
    CHAT_AGENT_STREAM_MAX_LENGTH,
    CHAT_AGENT_WORKFLOW_TIMEOUT,
    ChatAgentWorkflow,
    ChatAgentWorkflowInputs,
)
from posthog.temporal.ai.research_agent import (
    RESEARCH_AGENT_STREAM_MAX_LENGTH,
    RESEARCH_AGENT_WORKFLOW_TIMEOUT,
    ResearchAgentWorkflow,
    ResearchAgentWorkflowInputs,
)

from products.posthog_ai.backend.context_wrapper import (
    ALLOWED_TYPES as ALLOWED_ATTACHED_CONTEXT_TYPES,
    ContextService,
)
from products.posthog_ai.backend.message_routing import SandboxSession
from products.posthog_ai.backend.models.assistant import Conversation
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.contracts import TaskDetailDTO
from products.tasks.backend.facade.run_config import INITIAL_PERMISSION_MODE_CHOICES

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited
from ee.hogai.api.serializers import ConversationMinimalSerializer, ConversationSerializer
from ee.hogai.chat_agent import AssistantGraph
from ee.hogai.core.executor import AgentExecutor
from ee.hogai.queue import ConversationQueueMessage, ConversationQueueStore, QueueFullError, build_queue_message
from ee.hogai.stream.redis_stream import get_conversation_stream_key
from ee.hogai.utils.aio import async_to_sync
from ee.hogai.utils.feature_flags import has_sandbox_mode_feature_flag
from ee.hogai.utils.sse import AssistantSSESerializer
from ee.hogai.utils.types import PartialAssistantState

logger = structlog.get_logger(__name__)

RESEARCH_RATE_LIMIT_MESSAGE = (
    "You've reached the usage limit for Research mode, which is currently in beta "
    "with limited capacity. Please try again {retry_after}, or switch to a regular "
    "conversation for continued access."
)

STREAM_ITERATION_LATENCY_HISTOGRAM = Histogram(
    "posthog_ai_stream_iteration_latency_seconds",
    "Time between iterations in the async stream loop",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf")],
)


class MessageMinimalSerializer(serializers.Serializer):
    """Serializer for appending a message to an existing conversation without triggering AI processing."""

    content = serializers.CharField(required=True, max_length=10000)


def _strip_large_spend_history(billing_context: MaxBillingContext, threshold: int = 20) -> MaxBillingContext:
    """Large spend histories can exceed Temporal's 2MB payload limit."""
    if billing_context.spend_history and len(billing_context.spend_history) > threshold:
        billing_context.spend_history = None
    return billing_context


class MessageSerializer(MessageMinimalSerializer):
    content = serializers.CharField(
        required=True,
        allow_null=True,  # Null content means we're resuming streaming or continuing previous generation
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
    agent_mode = serializers.ChoiceField(required=False, choices=[mode.value for mode in AgentMode])
    is_sandbox = serializers.BooleanField(required=False, default=False)
    resume_payload = serializers.JSONField(required=False, allow_null=True)

    def validate(self, attrs):
        data = attrs
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
                billing_context = _strip_large_spend_history(MaxBillingContext.model_validate(billing_context))
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


class QueueMessageSerializer(serializers.Serializer):
    content = serializers.CharField(required=True, allow_blank=False, max_length=40000)
    contextual_tools = serializers.DictField(required=False, child=serializers.JSONField())
    ui_context = serializers.JSONField(required=False)
    billing_context = serializers.JSONField(required=False)
    agent_mode = serializers.ChoiceField(required=False, choices=[mode.value for mode in AgentMode])

    def validate(self, attrs):
        data = attrs
        try:
            HumanMessage.model_validate(
                {
                    "content": data["content"],
                    "ui_context": data.get("ui_context"),
                }
            )
        except pydantic.ValidationError:
            raise serializers.ValidationError("Invalid message content.")

        billing_context = data.get("billing_context")
        if billing_context:
            try:
                parsed_context = _strip_large_spend_history(MaxBillingContext.model_validate(billing_context))
                data["billing_context"] = parsed_context.model_dump()
            except pydantic.ValidationError as e:
                capture_exception(e)
                data["billing_context"] = None

        if agent_mode := data.get("agent_mode"):
            try:
                data["agent_mode"] = AgentMode(agent_mode).value
            except ValueError:
                raise serializers.ValidationError("Invalid agent mode.")

        return data


class QueueMessageUpdateSerializer(serializers.Serializer):
    content = serializers.CharField(required=True, allow_blank=False, max_length=40000)


class SandboxAttachedContextItemSerializer(serializers.Serializer):
    """One typed attachment carried by a sandbox message."""

    type = serializers.ChoiceField(
        choices=sorted(ALLOWED_ATTACHED_CONTEXT_TYPES),
        help_text="Attachment kind. Entity types carry `id` (+ optional `name`); `text` carries `value`.",
    )
    id = serializers.JSONField(
        required=False,
        help_text="Entity identifier — integer for `dashboard`/`action`, string short_id/UUID otherwise. Absent for `text`.",
    )
    name = serializers.CharField(
        required=False, help_text="Optional human-readable label rendered in the context block."
    )
    value = serializers.CharField(required=False, help_text="Free-text content. Only for `text` attachments.")


class SandboxOpenSerializer(serializers.Serializer):
    """Request body for `POST /conversations/{id}/open/`. A string `content` processes a turn; a
    null/absent `content` warms a sandbox that idles awaiting the first message."""

    content = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=40000,
        help_text="The user's message text. Omit or null to warm a sandbox (boot + idle) ahead of the first message.",
    )
    trace_id = serializers.UUIDField(
        required=False, help_text="Client-generated trace id correlated with the resulting Run's SSE stream."
    )
    attached_context = serializers.ListField(
        required=False,
        child=SandboxAttachedContextItemSerializer(),
        help_text="Typed PostHog entities (and free text) attached to this message.",
    )
    initial_permission_mode = serializers.ChoiceField(
        choices=INITIAL_PERMISSION_MODE_CHOICES,
        required=False,
        help_text=(
            "Initial permission mode for the sandbox agent session. "
            "Defaults to `auto`, which allows safe tool use while preserving explicit confirmations."
        ),
    )
    task_id = serializers.UUIDField(
        required=False,
        help_text=(
            "Bind a brand-new sandbox conversation to an existing Task so the first message resumes "
            "that Task's run. Honored only when this request creates the conversation row; ignored "
            "for an already-existing conversation."
        ),
    )

    def validate_task_id(self, value: uuid.UUID) -> uuid.UUID:
        """Resolve the Task to bind, scoped to the team and the requesting user's visibility.

        Mirrors the tasks API's `task_visibility_q` gate so a team member can't bind a conversation
        to a teammate's private task by guessing its id. Returns the validated id (consumed directly
        by the view), so an unreadable id surfaces as a 400 here rather than failing deeper in routing.
        """
        team = self.context["team"]
        user = self.context["user"]
        if not tasks_facade.task_visible(value, team.id, user.id):
            raise serializers.ValidationError("Task not found or not accessible.")
        return value


class SandboxMessageResponseSerializer(serializers.Serializer):
    """Response for `POST /conversations/{id}/open/` — the IDs the frontend opens SSE against."""

    task_id = serializers.CharField(help_text="The products/tasks Task backing the conversation.")
    run_id = serializers.CharField(help_text="The Run the frontend opens SSE against.")
    trace_id = serializers.CharField(allow_null=True, help_text="Echo of the request trace id, if provided.")
    run_status = serializers.CharField(help_text="Current status of the targeted Run (e.g. `queued`, `in_progress`).")
    just_created_run = serializers.BooleanField(
        help_text="True when a new Run was created (first message, terminal resume, or fresh warm); false for an in-progress follow-up or a reused warm Run."
    )


@extend_schema(tags=["max"])
class ConversationViewSet(
    TeamAndOrgViewSetMixin, ListModelMixin, RetrieveModelMixin, DestroyModelMixin, GenericViewSet
):
    scope_object = "conversation"
    serializer_class = ConversationSerializer
    queryset = Conversation.objects.all()
    lookup_url_kwarg = "conversation"

    def _queue_conversation_id(self) -> str:
        if not self.lookup_url_kwarg:
            raise exceptions.ValidationError("Conversation not provided")
        conversation_id = self.kwargs.get(self.lookup_url_kwarg)
        if not conversation_id:
            raise exceptions.ValidationError("Conversation not provided")
        return str(conversation_id)

    def _ensure_queue_access(self, request: Request, conversation_id: str) -> Response | None:
        try:
            # nosemgrep: idor-lookup-without-team (instance scoped to team via get_queryset)
            conversation = Conversation.objects.exclude(deleted=True).get(id=conversation_id)
        except Conversation.DoesNotExist:
            return Response({"error": "Conversation not found"}, status=status.HTTP_404_NOT_FOUND)
        if conversation.user != request.user or conversation.team != self.team:
            return Response({"error": "Cannot access other users' conversations"}, status=status.HTTP_403_FORBIDDEN)
        return None

    def _queue_response(self, queue_store: ConversationQueueStore, queue: list[ConversationQueueMessage]) -> Response:
        return Response({"messages": queue, "max_queue_messages": queue_store.max_messages})

    def safely_get_queryset(self, queryset):
        queryset = queryset.select_related("user").exclude(deleted=True)

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
        if self.action == "list":
            queryset = queryset.defer("approval_decisions", "messages_json", "sandbox_task_id", "sandbox_run_id")
        return queryset

    def get_throttles(self):
        # For message-sending / warming actions, throttling is handled in check_throttles() for conditional logic
        if self.action in ("create", "open"):
            return []
        return super().get_throttles()

    def _is_research_request(self, request: Request) -> bool:
        """Check if the request is for a research conversation."""
        # Check if it's a new conversation with research mode
        agent_mode = request.data.get("agent_mode")
        if agent_mode == AgentMode.RESEARCH or agent_mode == AgentMode.RESEARCH.value:
            return True

        # Check if it's an existing deep research conversation
        conversation_id = request.data.get("conversation")
        if conversation_id:
            try:
                conversation = Conversation.objects.exclude(deleted=True).get(id=conversation_id, team=self.team)
                if conversation.type == Conversation.Type.DEEP_RESEARCH:
                    return True
            except (Conversation.DoesNotExist, ValidationError):
                # DoesNotExist or ValidationError (invalid UUID) - not a research conversation
                pass

        return False

    def check_throttles(self, request: Request):
        # Apply the AI throttles to the message-sending / warming actions — `open` provisions a real
        # sandbox Run whether or not it carries a message, so it shares the same rate limit as `create`.
        if self.action not in ("create", "open"):
            return super().check_throttles(request)

        # Skip throttling in local development
        if settings.DEBUG:
            return

        # Determine which throttles to apply based on request type
        is_research = self._is_research_request(request)

        if is_research:
            if is_team_exempt_from_ai_rate_limit(self.team_id):
                return
            throttles = [AIResearchBurstRateThrottle(), AIResearchSustainedRateThrottle()]
        else:
            # Skip throttling for paying customers
            if self.organization.customer_id:
                return
            throttles = [AIBurstRateThrottle(), AISustainedRateThrottle()]

        for throttle in throttles:
            if not throttle.allow_request(request, self):
                wait = throttle.wait()
                if wait is not None:
                    if wait < 60:
                        retry_after = f"in {int(wait)} seconds"
                    elif wait < 3600:
                        retry_after = f"in {int(wait / 60)} minutes"
                    else:
                        retry_after = "later today"
                else:
                    retry_after = "later"

                if is_research:
                    detail = RESEARCH_RATE_LIMIT_MESSAGE.format(retry_after=retry_after)
                else:
                    detail = f"You've reached PostHog AI's usage limit for the moment. Please try again {retry_after}."

                raise Throttled(wait=wait, detail=detail)

    def get_serializer_class(self):
        if self.action == "create":
            return MessageSerializer
        if self.action == "append_message":
            return MessageMinimalSerializer
        if self.action == "list":
            return ConversationMinimalSerializer
        return super().get_serializer_class()

    def get_serializer(self, *args, **kwargs):
        if self.action in ("list", "retrieve") and args:
            context = kwargs.pop("context", self.get_serializer_context())
            context["conversation_task_dtos_by_id"] = self._conversation_task_dtos_by_id(args[0])
            kwargs["context"] = context
        return super().get_serializer(*args, **kwargs)

    def _conversation_task_dtos_by_id(self, instance) -> dict[str, TaskDetailDTO]:
        conversations = (
            [instance] if isinstance(instance, Conversation) else list(cast(Iterable[Conversation], instance))
        )
        task_ids = list({conversation.task_id for conversation in conversations if conversation.task_id is not None})
        return {
            str(task_id): task
            for task_id, task in tasks_facade.get_conversation_task_dtos(task_ids, self.team_id).items()
        }

    def get_serializer_context(self):
        context = super().get_serializer_context()
        # drf-spectacular introspects with a fake view (no URL kwargs), so `self.team` would
        # raise KeyError: 'team_id'. Skip the eager team/user lookup during schema generation.
        if getattr(self, "swagger_fake_view", False):
            return context
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
        is_research = serializer.validated_data.get("agent_mode") == AgentMode.RESEARCH

        is_new_conversation = False
        # Safely set the lookup kwarg for potential error handling
        if self.lookup_url_kwarg:
            self.kwargs[self.lookup_url_kwarg] = conversation_id
        try:
            # nosemgrep: idor-lookup-without-team, idor-taint-user-input-to-model-get (user+team check immediately after)
            conversation = Conversation.objects.get(id=conversation_id)
            if conversation.user != request.user or conversation.team != self.team:
                return Response(
                    {"error": "Cannot access other users' conversations"}, status=status.HTTP_400_BAD_REQUEST
                )
            if conversation.deleted:
                return Response({"error": "Conversation does not exist"}, status=status.HTTP_404_NOT_FOUND)
        except Conversation.DoesNotExist:
            # Conversation doesn't exist, create it if we have a message
            if not has_message:
                return Response(
                    {"error": "Cannot stream from non-existent conversation"}, status=status.HTTP_400_BAD_REQUEST
                )
            # Use frontend-provided conversation ID
            # Mark conversation as internal if created during an impersonated session (support agents)
            is_impersonated = is_impersonated_session(request)
            conversation_type = Conversation.Type.DEEP_RESEARCH if is_research else Conversation.Type.ASSISTANT
            # This endpoint is LangGraph-only — sandbox conversations are created via `open`. New rows
            # are always LangGraph (the model default), never stamped from the sandbox flag here.
            conversation = Conversation.objects.create(
                user=cast(User, request.user),
                team=self.team,
                id=conversation_id,
                type=conversation_type,
                is_internal=is_impersonated,
                agent_runtime=Conversation.AgentRuntime.LANGGRAPH,
            )
            is_new_conversation = True

        is_idle = conversation.status == Conversation.Status.IDLE
        has_message = serializer.validated_data.get("message") is not None
        has_resume_payload = serializer.validated_data.get("resume_payload") is not None

        # Sandbox conversations — including the legacy LangGraph→sandbox conversion of a reopened
        # thread — are served exclusively by the `open` endpoint. Reject any that reach this one,
        # whether an already-sandbox row or a sandbox-signalling body, so a sandbox conversation can
        # never fall through to the LangGraph workflow below.
        if (
            conversation.agent_runtime == Conversation.AgentRuntime.SANDBOX
            or serializer.validated_data.get("is_sandbox", False)
            or serializer.validated_data.get("agent_mode") == AgentMode.SANDBOX
        ):
            raise exceptions.ValidationError("Sandbox conversations must be opened via the open endpoint.")

        if conversation.type == Conversation.Type.DEEP_RESEARCH:
            if not is_new_conversation and is_idle and has_message and not has_resume_payload:
                conversation.type = Conversation.Type.ASSISTANT
                conversation.save(update_fields=["type", "updated_at"])
                is_research = False
            else:
                is_research = True

        if has_message and not is_idle:
            raise Conflict("Cannot resume streaming with a new message")
        # If the frontend is trying to resume streaming for a finished conversation, return a conflict error
        if not has_message and conversation.status == Conversation.Status.IDLE and not has_resume_payload:
            raise exceptions.ValidationError("Cannot continue streaming from an idle conversation")

        is_impersonated = is_impersonated_session(request)

        workflow_inputs: ChatAgentWorkflowInputs | ResearchAgentWorkflowInputs
        workflow_class: type[ChatAgentWorkflow] | type[ResearchAgentWorkflow]
        if is_research:
            workflow_inputs = ResearchAgentWorkflowInputs(
                team_id=self.team_id,
                user_id=cast(User, request.user).pk,  # Use pk instead of id for User model
                conversation_id=conversation.id,
                stream_key=get_conversation_stream_key(conversation.id),
                message=serializer.validated_data["message"].model_dump() if has_message else None,
                is_new_conversation=is_new_conversation,
                trace_id=serializer.validated_data["trace_id"],
                session_id=request.headers.get("X-POSTHOG-SESSION-ID"),  # Relies on posthog-js __add_tracing_headers
                billing_context=serializer.validated_data.get("billing_context"),
                is_agent_billable=False,
                is_impersonated=is_impersonated,
                resume_payload=serializer.validated_data.get("resume_payload"),
            )
            workflow_class = ResearchAgentWorkflow
            timeout = RESEARCH_AGENT_WORKFLOW_TIMEOUT
            max_length = RESEARCH_AGENT_STREAM_MAX_LENGTH
        else:
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
                is_impersonated=is_impersonated,
                resume_payload=serializer.validated_data.get("resume_payload"),
            )
            workflow_class = ChatAgentWorkflow
            timeout = CHAT_AGENT_WORKFLOW_TIMEOUT
            max_length = CHAT_AGENT_STREAM_MAX_LENGTH

        async def async_stream(
            workflow_inputs: ChatAgentWorkflowInputs | ResearchAgentWorkflowInputs,
        ) -> AsyncGenerator[bytes]:
            SSE_KEEPALIVE_COMMENT = b": keepalive\n\n"
            SSE_KEEPALIVE_INTERVAL = 15  # seconds — well under typical LB idle timeouts (60s)

            serializer = AssistantSSESerializer()
            stream_manager = AgentExecutor(conversation, timeout=timeout, max_length=max_length)
            last_yield_time = time.time()
            last_chunk_time = last_yield_time
            aiter = stream_manager.astream(workflow_class, workflow_inputs).__aiter__()

            while True:
                next_task = asyncio.ensure_future(aiter.__anext__())
                try:
                    while not next_task.done():
                        elapsed = time.time() - last_yield_time
                        wait_time = max(0.1, SSE_KEEPALIVE_INTERVAL - elapsed)
                        done, _ = await asyncio.wait({next_task}, timeout=wait_time)
                        if not done:
                            yield SSE_KEEPALIVE_COMMENT
                            last_yield_time = time.time()
                except BaseException:
                    if not next_task.done():
                        next_task.cancel()
                    raise

                try:
                    chunk = next_task.result()
                except StopAsyncIteration:
                    break

                now = time.time()
                STREAM_ITERATION_LATENCY_HISTOGRAM.observe(now - last_chunk_time)
                last_chunk_time = now
                last_yield_time = now

                event = await serializer.dumps(chunk)
                yield event.encode("utf-8")

        return sse_streaming_response(
            async_stream(workflow_inputs)
            if settings.SERVER_GATEWAY_INTERFACE == "ASGI"
            else async_to_sync(lambda: async_stream(workflow_inputs)),
            endpoint="max_conversation",
        )

    @action(detail=True, methods=["GET", "POST"], url_path="queue")
    def queue(self, request: Request, *args, **kwargs):
        conversation_id = self._queue_conversation_id()
        error_response = self._ensure_queue_access(request, conversation_id)
        if error_response:
            return error_response

        queue_store = ConversationQueueStore(conversation_id)

        if request.method == "GET":
            return self._queue_response(queue_store, queue_store.list())

        serializer = QueueMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = build_queue_message(
            content=serializer.validated_data["content"],
            contextual_tools=serializer.validated_data.get("contextual_tools"),
            ui_context=serializer.validated_data.get("ui_context"),
            billing_context=serializer.validated_data.get("billing_context"),
            agent_mode=serializer.validated_data.get("agent_mode"),
            session_id=request.headers.get("X-POSTHOG-SESSION-ID"),
        )

        try:
            queue = queue_store.enqueue(message)
        except QueueFullError:
            return Response(
                {
                    "error": "queue_full",
                    "detail": "Only two messages can be queued at a time.",
                },
                status=status.HTTP_409_CONFLICT,
            )

        return self._queue_response(queue_store, queue)

    @extend_schema(parameters=[OpenApiParameter("queue_id", OpenApiTypes.STR, OpenApiParameter.PATH)])
    @action(detail=True, methods=["PATCH", "DELETE"], url_path=r"queue/(?P<queue_id>[^/.]+)")
    def queue_item(self, request: Request, queue_id: str, *args, **kwargs):
        conversation_id = self._queue_conversation_id()
        error_response = self._ensure_queue_access(request, conversation_id)
        if error_response:
            return error_response

        queue_store = ConversationQueueStore(conversation_id)
        queue = queue_store.list()
        queue_index = next((index for index, item in enumerate(queue) if item.get("id") == queue_id), None)

        if queue_index is None:
            return Response({"detail": "Queue message not found."}, status=status.HTTP_404_NOT_FOUND)

        if request.method == "PATCH":
            serializer = QueueMessageUpdateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            queue = queue_store.update(queue_id, serializer.validated_data["content"])
        else:
            queue = queue_store.delete(queue_id)

        return self._queue_response(queue_store, queue)

    @action(detail=True, methods=["POST"], url_path="queue/clear")
    def clear_queue(self, request: Request, *args, **kwargs):
        conversation_id = self._queue_conversation_id()
        error_response = self._ensure_queue_access(request, conversation_id)
        if error_response:
            return error_response
        queue_store = ConversationQueueStore(conversation_id)
        return self._queue_response(queue_store, queue_store.clear())

    @extend_schema(
        request=SandboxOpenSerializer,
        responses={
            200: SandboxMessageResponseSerializer,
            204: OpenApiResponse(description="Warm request that provisioned nothing (pool full / released)."),
            400: OpenApiResponse(description="Conversation is not on the sandbox runtime."),
        },
        description=(
            "Create-or-resume a sandbox conversation — the single sandbox session opener. With `content`, "
            "processes the turn (first message, in-progress follow-up, or terminal resume); without `content`, "
            "warms a sandbox that idles awaiting the first message. Returns the `(task, run)` handle the "
            "frontend opens SSE against. The conversation row is created on first use from the URL id."
        ),
    )
    @action(detail=True, methods=["POST"], url_path="open")
    def open(self, request: Request, *args, **kwargs):
        # Both warming and messaging launch a Run, so gate both on the AI-credit quota.
        if is_team_limited(self.team.api_token, QuotaResource.AI_CREDITS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY):
            raise QuotaLimitExceeded(
                "Your organization reached its AI credit usage limit. Increase the limits in Billing settings, or ask an org admin to do so."
            )
        serializer = SandboxOpenSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)

        conversation, created = self._get_or_create_sandbox_conversation(
            request, bind_task=serializer.validated_data.get("task_id")
        )
        has_content = bool(serializer.validated_data.get("content"))
        convert_to_acp, resumed_context = self._compute_sandbox_conversion(request, conversation, has_content)

        # Sandbox-only endpoint. A converting LangGraph thread is still LANGGRAPH here (the flip happens
        # inside the routing service), so allow it through; reject any other non-sandbox conversation.
        if conversation.agent_runtime != Conversation.AgentRuntime.SANDBOX and not convert_to_acp:
            raise exceptions.ValidationError("This conversation is not on the sandbox runtime.")

        if has_content and conversation.title is None:
            conversation.title = serializer.validated_data["content"][:80]
            conversation.save(update_fields=["title"])

        return self._route_sandbox_message(
            request, conversation, resumed_context=resumed_context, convert_to_acp=convert_to_acp, created=created
        )

    def _get_or_create_sandbox_conversation(
        self, request: Request, *, bind_task: uuid.UUID | None = None
    ) -> tuple[Conversation, bool]:
        """Resolve the URL-keyed conversation, creating it on first use (the client mints the id).

        `open` is create-or-resume: a brand-new conversation (first warm or first message) has no row
        yet, so a plain `get_object()` would 404. A brand-new row is only born on the sandbox runtime,
        and only for a sandbox-eligible caller — otherwise we'd persist an orphaned LangGraph row that
        `open` immediately rejects. Returns whether the row was created this request so the caller can
        drop it again if nothing ends up being provisioned.

        `bind_task` (already validated for team + visibility by `SandboxOpenSerializer`) binds the new
        row to an existing Task, so the first message resumes that Task's run instead of starting a
        fresh task. It only applies on create — an existing conversation keeps the Task it was born with.
        """
        conversation_id = self.kwargs[self.lookup_url_kwarg]
        user = cast(User, request.user)
        try:
            # nosemgrep: idor-lookup-without-team, idor-taint-user-input-to-model-get (user+team checked below)
            conversation = Conversation.objects.get(id=conversation_id)
        except Conversation.DoesNotExist:
            # Gate first-use creation on eligibility so a non-sandbox caller can't spam orphaned rows
            # by POSTing `open` with random ids — `open` would create then reject each one otherwise.
            if not has_sandbox_mode_feature_flag(self.team, user):
                raise exceptions.ValidationError("This conversation is not on the sandbox runtime.")
            conversation = Conversation.objects.create(
                user=user,
                team=self.team,
                id=conversation_id,
                type=Conversation.Type.ASSISTANT,
                is_internal=is_impersonated_session(request),
                agent_runtime=Conversation.AgentRuntime.SANDBOX,
                task_id=bind_task,
            )
            return conversation, True
        if conversation.user != user or conversation.team != self.team:
            raise exceptions.PermissionDenied("Cannot access other users' conversations")
        if conversation.deleted:
            raise exceptions.NotFound("Conversation does not exist")
        return conversation, False

    def _compute_sandbox_conversion(
        self, request: Request, conversation: Conversation, has_content: bool
    ) -> tuple[bool, str | None]:
        """Detect + prepare a legacy LangGraph→sandbox conversion on the first new message.

        A reopened LangGraph thread converts to sandbox on its first message: read the current
        conversation window into a one-time resumed-context block (while still LangGraph), then the
        routing service flips the runtime + links the Task atomically. Warm (`content`-less) never
        converts. A failed read never blocks — the user continues, the legacy thread stays rendered.
        """
        convert_to_acp = bool(
            has_content
            and conversation.agent_runtime == Conversation.AgentRuntime.LANGGRAPH
            and conversation.task_id is None
            and conversation.status == Conversation.Status.IDLE
            and has_sandbox_mode_feature_flag(self.team, cast(User, request.user))
        )
        if not convert_to_acp:
            return False, None
        try:
            resumed_context = asgi_async_to_sync(ContextService().abuild_resumed_legacy_context)(
                conversation, self.team, cast(User, request.user)
            )
        except Exception as e:
            # A failed read must not block the conversion — continue with no resumed context.
            capture_exception(e)
            resumed_context = None
        return True, resumed_context

    def _auto_route_repository(self, request: Request, conversation: Conversation, user: User) -> str | None:
        """Auto-select the repository a sandbox conversation's first message is about.

        Runs only on a first message — no backing Task yet (`task_id is None`) and real content.
        Followups and resumes reuse the existing Task's repository, and warming has no message to
        route on, so neither triggers the explicit repository mention match. Selection never raises;
        any failure degrades to None — a repo-less sandbox — so it can't block the conversation.
        """
        if conversation.task_id is not None:
            return None
        content = request.data.get("content")
        if not isinstance(content, str) or not content.strip():
            return None
        return asgi_async_to_sync(tasks_facade.select_repository_for_message)(
            self.team_id, user.pk, content, origin_product=tasks_facade.TaskOriginProduct.POSTHOG_AI
        )

    def _route_sandbox_message(
        self,
        request: Request,
        conversation: Conversation,
        *,
        resumed_context: str | None = None,
        convert_to_acp: bool = False,
        created: bool = False,
    ) -> Response:
        user = cast(User, request.user)
        repository = self._auto_route_repository(request, conversation, user)
        result = SandboxSession(conversation, user).open(
            request.data, resumed_context=resumed_context, convert_to_acp=convert_to_acp, repository=repository
        )
        if result is None:
            # Warm intent that provisioned nothing (pool full / released) — no run to open. Drop the
            # row if we created it this request so a content-less warm can't leave orphaned conversations.
            if created:
                conversation.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        content = request.data.get("content")
        if isinstance(content, str) and content.strip():
            report_user_action(
                user,
                "prompt sent",
                {
                    "trace_id": result.trace_id,
                    "conversation_id": str(conversation.id),
                    "execution_type": "sandbox",
                    "agent_runtime": "sandbox",
                    "converted_to_acp": convert_to_acp,
                    "just_created_run": result.just_created_run,
                    "has_attached_context": result.attached_context_count > 0,
                    "attached_context_count": result.attached_context_count,
                },
                team=self.team,
                request=request,
            )
        # attached_context_count is internal telemetry plumbing — keep it out of the response body.
        return Response(result.model_dump(exclude={"attached_context_count"}), status=status.HTTP_200_OK)

    @extend_schema(
        description="Cancel the conversation's in-progress LangGraph run.",
        responses={
            204: OpenApiResponse(description="Cancellation accepted, or already cancelling."),
            422: OpenApiResponse(description="Failed to cancel the conversation."),
        },
    )
    @action(detail=True, methods=["PATCH"])
    def cancel(self, request: Request, *args, **kwargs):
        # Sandbox runs cancel through the generic tasks relay (`runs/{run}/command/`); this endpoint
        # serves the LangGraph runtime only.
        conversation = self.get_object()

        # IDLE is intentionally not short-circuited: during the handoff between the main
        # workflow completing and a queued workflow starting, the status is briefly IDLE
        # even though a queued Temporal workflow may be running.
        if conversation.status == Conversation.Status.CANCELING:
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

    @extend_schema(
        description="Delete a conversation.",
        responses={204: None},
    )
    def destroy(self, request: Request, *args, **kwargs) -> Response:
        instance: Conversation = self.get_object()
        Conversation.objects.filter(pk=instance.pk).update(deleted=True, deleted_at=timezone.now())
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
