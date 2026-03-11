import json
import time
import uuid
import asyncio
from collections.abc import AsyncGenerator
from typing import Any, cast

from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import StreamingHttpResponse

import pydantic
import structlog
from asgiref.sync import async_to_sync as asgi_async_to_sync
from django_redis import get_redis_connection
from drf_spectacular.utils import extend_schema
from loginas.utils import is_impersonated_session
from prometheus_client import Histogram
from rest_framework import exceptions, serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import Throttled
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.schema import AgentMode, AssistantEventType, AssistantMessage, HumanMessage, MaxBillingContext

from posthog.api.routing import TeamAndOrgViewSetMixin
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
from posthog.temporal.common.client import sync_connect

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.stream.redis_stream import TaskRunRedisStream, TaskRunStreamError, get_task_run_stream_key
from products.tasks.backend.temporal.client import execute_task_processing_workflow
from products.tasks.backend.temporal.process_task.workflow import ProcessTaskWorkflow

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited
from ee.hogai.api.serializers import ConversationMinimalSerializer, ConversationSerializer
from ee.hogai.chat_agent import AssistantGraph
from ee.hogai.core.executor import AgentExecutor
from ee.hogai.queue import ConversationQueueMessage, ConversationQueueStore, QueueFullError, build_queue_message
from ee.hogai.sandbox.mapping import get_sandbox_mapping, set_sandbox_mapping
from ee.hogai.stream.redis_stream import get_conversation_stream_key
from ee.hogai.utils.aio import async_to_sync
from ee.hogai.utils.feature_flags import has_sandbox_mode_feature_flag
from ee.hogai.utils.sse import AssistantSSESerializer
from ee.hogai.utils.types import PartialAssistantState
from ee.models.assistant import Conversation

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
                parsed_context = MaxBillingContext.model_validate(billing_context)
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


@extend_schema(tags=["max"])
class ConversationViewSet(TeamAndOrgViewSetMixin, ListModelMixin, RetrieveModelMixin, GenericViewSet):
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
            conversation = Conversation.objects.get(id=conversation_id)
        except Conversation.DoesNotExist:
            return Response({"error": "Conversation not found"}, status=status.HTTP_404_NOT_FOUND)
        if conversation.user != request.user or conversation.team != self.team:
            return Response({"error": "Cannot access other users' conversations"}, status=status.HTTP_403_FORBIDDEN)
        return None

    def _queue_response(self, queue_store: ConversationQueueStore, queue: list[ConversationQueueMessage]) -> Response:
        return Response({"messages": queue, "max_queue_messages": queue_store.max_messages})

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
        # For create action, throttling is handled in check_throttles() for conditional logic
        if self.action == "create":
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
                conversation = Conversation.objects.get(id=conversation_id, team=self.team)
                if conversation.type == Conversation.Type.DEEP_RESEARCH:
                    return True
            except (Conversation.DoesNotExist, ValidationError):
                # DoesNotExist or ValidationError (invalid UUID) - not a research conversation
                pass

        return False

    def check_throttles(self, request: Request):
        # Only apply custom throttling for create action
        if self.action != "create":
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
        is_sandbox = serializer.validated_data.get("agent_mode") == AgentMode.SANDBOX

        if conversation.type == Conversation.Type.DEEP_RESEARCH:
            if not is_new_conversation and is_idle and has_message and not has_resume_payload:
                conversation.type = Conversation.Type.ASSISTANT
                conversation.save(update_fields=["type", "updated_at"])
                is_research = False
            else:
                is_research = True

        if has_message and not is_idle and not is_sandbox:
            raise Conflict("Cannot resume streaming with a new message")
        # If the frontend is trying to resume streaming for a finished conversation, return a conflict error
        if not has_message and conversation.status == Conversation.Status.IDLE and not has_resume_payload:
            raise exceptions.ValidationError("Cannot continue streaming from an idle conversation")

        is_impersonated = is_impersonated_session(request)

        if is_sandbox and has_message:
            if not settings.DEBUG and not has_sandbox_mode_feature_flag(self.team, cast(User, request.user)):
                raise exceptions.PermissionDenied("Sandbox mode is not enabled for this user.")

            content = serializer.validated_data["content"]

            if is_new_conversation:
                conversation.title = content[:80]
                conversation.save(update_fields=["title"])

            mapping = get_sandbox_mapping(str(conversation_id))

            # Reconstruct mapping from conversation fields if Redis expired
            if not mapping and conversation.sandbox_task_id and conversation.sandbox_run_id:
                mapping = {
                    "task_id": str(conversation.sandbox_task_id),
                    "run_id": str(conversation.sandbox_run_id),
                }

            start_id = "0"

            if mapping:
                run_id = mapping["run_id"]
                start_id = _get_latest_stream_id(run_id)

                try:
                    task_run = TaskRun.objects.select_related("task").get(id=run_id, team=self.team)
                except TaskRun.DoesNotExist:
                    raise exceptions.ValidationError("Sandbox session no longer exists.")

                if task_run.is_terminal:
                    snapshot_ext_id = (task_run.state or {}).get("snapshot_external_id")
                    if not snapshot_ext_id:
                        raise exceptions.ValidationError("Sandbox session has ended and no snapshot is available.")

                    task = task_run.task
                    new_run = task.create_run(
                        mode="interactive",
                        extra_state={
                            "snapshot_external_id": snapshot_ext_id,
                            "resume_from_run_id": str(task_run.id),
                            "pending_user_message": content,
                        },
                    )
                    run_id = str(new_run.id)

                    conversation.sandbox_run_id = new_run.id
                    conversation.save(update_fields=["sandbox_run_id"])

                    set_sandbox_mapping(str(conversation_id), str(task.id), run_id)

                    execute_task_processing_workflow(
                        task_id=str(task.id),
                        run_id=run_id,
                        team_id=task.team_id,
                        user_id=cast(User, request.user).pk,
                        create_pr=False,
                    )

                    _seed_sandbox_stream(run_id)
                    start_id = "0"

                    conv_data = json.dumps(ConversationMinimalSerializer(conversation).data)
                    logger.info(
                        "sandbox_view_returning_resume_stream",
                        run_id=run_id,
                        conversation_id=str(conversation_id),
                    )
                    return StreamingHttpResponse(
                        (
                            _sandbox_stream(
                                conv_data, run_id, start_id, str(conversation_id), content, team_id=self.team.id
                            )
                            if settings.SERVER_GATEWAY_INTERFACE == "ASGI"
                            else async_to_sync(
                                lambda: _sandbox_stream(
                                    conv_data, run_id, start_id, str(conversation_id), content, team_id=self.team.id
                                )
                            )
                        ),
                        content_type="text/event-stream",
                    )

                # Signal the Temporal workflow to send the follow-up message
                try:
                    client = sync_connect()
                    handle = client.get_workflow_handle(task_run.workflow_id)

                    async def _send_signal():
                        await handle.signal(ProcessTaskWorkflow.send_followup_message, content)

                    asgi_async_to_sync(_send_signal)()
                except Exception as e:
                    logger.warning(
                        "sandbox_followup_signal_failed",
                        run_id=run_id,
                        error=str(e),
                    )
            else:
                # First message: create task + run
                # TODO(@tatoalo): hardcoding repo for now, already built repo selection wiring
                try:
                    task = Task.create_and_run(
                        team=self.team,
                        title=content[:80],
                        description=content,
                        origin_product=Task.OriginProduct.USER_CREATED,
                        user_id=cast(User, request.user).pk,
                        repository="posthog/posthog",
                        create_pr=False,
                        mode="interactive",
                        start_workflow=True,
                    )
                except ValueError:
                    raise exceptions.ValidationError("Failed to create sandbox task.")

                task_run_or_none = task.latest_run
                if not task_run_or_none:
                    raise exceptions.ValidationError("Failed to create sandbox task run.")
                task_run = task_run_or_none

                run_id = str(task_run.id)
                set_sandbox_mapping(str(conversation_id), str(task.id), run_id)

                conversation.sandbox_task_id = task.id
                conversation.sandbox_run_id = task_run.id
                conversation.save(update_fields=["sandbox_task_id", "sandbox_run_id"])

                _seed_sandbox_stream(run_id)

            conv_data = json.dumps(ConversationMinimalSerializer(conversation).data)

            logger.info(
                "sandbox_view_returning_stream",
                run_id=run_id,
                conversation_id=str(conversation_id),
                start_id=start_id,
                gateway=settings.SERVER_GATEWAY_INTERFACE,
            )
            return StreamingHttpResponse(
                (
                    _sandbox_stream(conv_data, run_id, start_id, str(conversation_id), content, team_id=self.team.id)
                    if settings.SERVER_GATEWAY_INTERFACE == "ASGI"
                    else async_to_sync(
                        lambda: _sandbox_stream(
                            conv_data, run_id, start_id, str(conversation_id), content, team_id=self.team.id
                        )
                    )
                ),
                content_type="text/event-stream",
            )

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
        ) -> AsyncGenerator[bytes, None]:
            serializer = AssistantSSESerializer()
            stream_manager = AgentExecutor(conversation, timeout=timeout, max_length=max_length)
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

    @action(detail=True, methods=["PATCH"])
    def cancel(self, request: Request, *args, **kwargs):
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


def _get_latest_stream_id(run_id: str) -> str:
    """Return the latest entry ID in the task-run Redis stream.

    Used for follow-up messages so we only read events generated AFTER
    the current position (avoiding replay of previous turns).
    """
    stream_key = get_task_run_stream_key(run_id)
    conn = get_redis_connection("default")
    try:
        entries = conn.xrevrange(stream_key, count=1)
        if entries:
            return entries[0][0].decode()
    except Exception:
        logger.warning("_get_latest_stream_id_failed", run_id=run_id, exc_info=True)
    return "0"


def _seed_sandbox_stream(run_id: str) -> None:
    """Write a seed event to the Redis stream so it exists before the relay starts.

    Uses the sync Redis connection (safe in WSGI context).  The seed event has
    type=STREAM_STATUS with a non-terminal status, so ``read_stream`` silently
    skips it.
    """
    stream_key = get_task_run_stream_key(run_id)
    conn = get_redis_connection("default")
    conn.xadd(
        stream_key,
        {"data": json.dumps({"type": "STREAM_STATUS", "status": "initializing"})},
        maxlen=2000,
    )
    conn.expire(stream_key, 3600)


SANDBOX_TURN_IDLE_TIMEOUT = 60  # seconds of silence before ending the per-turn stream (safety fallback)

_TURN_COMPLETE_METHOD = "_posthog/turn_complete"


def _is_turn_complete(event: dict) -> bool:
    if event.get("type") != "notification":
        return False
    notification = event.get("notification", {})
    return notification.get("method") == _TURN_COMPLETE_METHOD


async def _sandbox_stream(
    conv_data: str,
    run_id: str,
    start_id: str = "0",
    conversation_id: str | None = None,
    user_content: str | None = None,
    team_id: int | None = None,
) -> AsyncGenerator[bytes, None]:
    """Stream sandbox events from Redis to the browser as SSE.

    Reads events in a background task and funnels them through an
    :class:`asyncio.Queue`.  An idle timeout on the *queue* (not on the
    async-generator) detects when the agent's turn is complete without
    corrupting the underlying Redis reader.

    Args:
        conv_data: Pre-serialized conversation JSON (serialized in sync context).
        run_id: The TaskRun ID whose Redis stream to read from.
        start_id: Redis stream ID to start reading from.
            ``"0"`` replays from the beginning (first message).
            A specific ID resumes from that position (follow-up messages).
        conversation_id: If provided, persist messages on the Conversation after the turn.
        user_content: The user message content to persist alongside the agent response.
    """
    logger.info("sandbox_stream_started", run_id=run_id, start_id=start_id)

    # Emit conversation event so the frontend gets the conversation ID
    yield f"event: {AssistantEventType.CONVERSATION}\ndata: {conv_data}\n\n".encode()

    stream_key = get_task_run_stream_key(run_id)
    redis_stream = TaskRunRedisStream(stream_key)

    if not await redis_stream.wait_for_stream():
        logger.warning("sandbox_stream_wait_timeout", stream_key=stream_key, run_id=run_id)
        error_data = json.dumps({"type": "generation_error"})
        yield f"event: {AssistantEventType.STATUS}\ndata: {error_data}\n\n".encode()
        return

    logger.info("sandbox_stream_connected", stream_key=stream_key)

    # Use a queue to decouple the idle-timeout from the async generator.
    # asyncio.wait_for on __anext__() would cancel and close the generator,
    # so we run the reader in a background task instead.
    _SENTINEL: dict = {}  # identity sentinel for stream end
    event_queue: asyncio.Queue[dict] = asyncio.Queue()

    async def _reader() -> None:
        try:
            async for ev in redis_stream.read_stream(start_id=start_id):
                await event_queue.put(ev)
        except TaskRunStreamError as exc:
            await event_queue.put({"_error": str(exc)})
        finally:
            await event_queue.put(_SENTINEL)

    reader_task = asyncio.create_task(_reader())
    agent_text_chunks: list[str] = []

    try:
        event_count = 0
        saw_data = False
        while True:
            try:
                event = await asyncio.wait_for(
                    event_queue.get(),
                    timeout=SANDBOX_TURN_IDLE_TIMEOUT,
                )
            except TimeoutError:
                if saw_data:
                    logger.info("sandbox_stream_turn_idle", run_id=run_id, total_events=event_count)
                    break
                # Haven't seen any data yet; keep waiting (sandbox still booting)
                continue

            if event is _SENTINEL:
                logger.info("sandbox_stream_completed", run_id=run_id, total_events=event_count)
                break

            if "_error" in event:
                logger.warning("sandbox_stream_error", run_id=run_id, error=event["_error"])
                error_data = json.dumps({"type": "generation_error"})
                yield f"event: {AssistantEventType.STATUS}\ndata: {error_data}\n\n".encode()
                break

            event_count += 1
            saw_data = True

            # Accumulate agent text for message persistence
            _accumulate_agent_text(event, agent_text_chunks)

            if event_count <= 3:
                logger.info(
                    "sandbox_stream_event",
                    run_id=run_id,
                    event_count=event_count,
                    event_type=event.get("type"),
                    notification_method=(
                        event.get("notification", {}).get("method") if event.get("type") == "notification" else None
                    ),
                )
            event_data = json.dumps(event)
            yield f"event: {AssistantEventType.SANDBOX}\ndata: {event_data}\n\n".encode()

            if _is_turn_complete(event):
                logger.info("sandbox_stream_turn_complete", run_id=run_id, total_events=event_count)
                break
    finally:
        reader_task.cancel()
        try:
            await reader_task
        except asyncio.CancelledError:
            pass

        # Persist messages after the turn completes
        if conversation_id:
            agent_text = "".join(agent_text_chunks)
            await _persist_sandbox_turn(conversation_id, user_content, agent_text, team_id=team_id)


async def _sandbox_error_stream(conv_data: str, error_message: str) -> AsyncGenerator[bytes, None]:
    """Emit a conversation event followed by an error, for when the sandbox command fails."""
    yield f"event: {AssistantEventType.CONVERSATION}\ndata: {conv_data}\n\n".encode()
    error_data = json.dumps({"type": "generation_error", "message": error_message})
    yield f"event: {AssistantEventType.STATUS}\ndata: {error_data}\n\n".encode()


def _accumulate_agent_text(event: dict, chunks: list[str]) -> None:
    """Extract agent message text from session/update notifications."""
    if event.get("type") != "notification":
        return
    notification = event.get("notification", {})
    if notification.get("method") != "session/update":
        return
    params = notification.get("params", {})
    update = params.get("update", {}) if isinstance(params, dict) else {}
    if not isinstance(update, dict):
        return
    if update.get("sessionUpdate") != "agent_message_chunk":
        return
    content = update.get("content")
    if isinstance(content, dict) and content.get("type") == "text":
        text = content.get("text", "")
        if text:
            chunks.append(text)


async def _persist_sandbox_turn(
    conversation_id: str, user_content: str | None, agent_text: str, team_id: int | None = None
) -> None:
    """Persist user and agent messages on the Conversation after a sandbox turn."""
    try:
        lookup: dict[str, Any] = {"id": conversation_id}
        if team_id is not None:
            lookup["team_id"] = team_id
        conversation = await Conversation.objects.aget(**lookup)
        messages: list[dict[str, Any]] = conversation.messages_json or []
        if user_content:
            messages.append({"type": "human", "content": user_content, "id": str(uuid.uuid4())})
        if agent_text:
            messages.append({"type": "ai", "content": agent_text, "id": f"sandbox-{uuid.uuid4()}"})
        conversation.messages_json = messages
        await conversation.asave(update_fields=["messages_json"])
    except Exception as e:
        logger.warning("persist_sandbox_turn_failed", conversation_id=conversation_id, error=str(e))
