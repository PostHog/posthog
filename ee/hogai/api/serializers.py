from typing import Any

import pydantic
from asgiref.sync import async_to_sync
from drf_spectacular.utils import extend_schema_field
from langgraph.graph.state import CompiledStateGraph
from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer
from posthog.exceptions_capture import capture_exception

from products.posthog_ai.backend.models.assistant import Conversation
from products.tasks.backend.models import Task
from products.tasks.backend.serializers import TaskSerializer

from ee.hogai.artifacts.manager import ArtifactManager
from ee.hogai.chat_agent import AssistantGraph
from ee.hogai.research_agent.graph import ResearchAgentGraph
from ee.hogai.tool import PENDING_APPROVAL_STATUS
from ee.hogai.utils.helpers import should_output_assistant_message
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.composed import AssistantMaxGraphState

# Sentinel: tells an absent queryset annotation apart from one that is present but None.
_UNSET = object()

_conversation_fields = [
    "id",
    "status",
    "title",
    "topic",
    "user",
    "created_at",
    "updated_at",
    "type",
    "is_internal",
    "slack_thread_key",
    "slack_workspace_domain",
]


CONVERSATION_TYPE_MAP: dict[
    Conversation.Type, tuple[type[AssistantGraph | ResearchAgentGraph], type[AssistantMaxGraphState]]
] = {
    Conversation.Type.ASSISTANT: (AssistantGraph, AssistantState),
    Conversation.Type.TOOL_CALL: (AssistantGraph, AssistantState),
    Conversation.Type.SLACK: (AssistantGraph, AssistantState),
    Conversation.Type.DEEP_RESEARCH: (ResearchAgentGraph, AssistantState),
}


async def aget_conversation_state(
    conversation: Conversation, team: Any, user: Any
) -> tuple[AssistantMaxGraphState | None, bool, dict[str, dict[str, Any]]]:
    """Compile the LangGraph graph, replay the checkpoint, and validate the typed state.

    Single source of truth for the LangGraph history read path — both the conversation
    serializer (history-load) and the legacy-history converter (products/posthog_ai) call this so
    the graph-compile + checkpoint-replay logic is never duplicated.

    Returns (state, has_unsupported_content, interrupt_payloads). `state` is None for sandbox
    conversations (no checkpoint) and on any read/validation error — errors degrade gracefully
    and are captured rather than raised so a bad checkpoint can't 500 a conversation load.
    """
    # Sandbox conversations have no LangGraph checkpoint — their state lives in S3 ACP logs.
    if conversation.agent_runtime == Conversation.AgentRuntime.SANDBOX:
        return None, False, {}

    try:
        graph_class, state_class = CONVERSATION_TYPE_MAP[conversation.type]  # type: ignore[index]
        graph: CompiledStateGraph = graph_class(team, user).compile_full_graph()
        snapshot = await graph.aget_state({"configurable": {"thread_id": str(conversation.id), "checkpoint_ns": ""}})
        state = state_class.model_validate(snapshot.values)

        # Extract interrupt payloads from pending tasks — the single source of truth for payload data.
        interrupt_payloads: dict[str, dict[str, Any]] = {}
        for task in snapshot.tasks:
            for interrupt in task.interrupts:
                if isinstance(interrupt.value, dict) and interrupt.value.get("status") == PENDING_APPROVAL_STATUS:
                    proposal_id = interrupt.value.get("proposal_id")
                    if proposal_id:
                        interrupt_payloads[proposal_id] = interrupt.value

        return state, False, interrupt_payloads
    except pydantic.ValidationError as e:
        capture_exception(
            e,
            additional_properties={
                "tag": "max_ai",
                "exception_type": "ValidationError",
                "conversation_id": str(conversation.id),
            },
        )
        return None, True, {}
    except Exception as e:
        # Broad exception handler to gracefully degrade UI instead of 500s.
        # Captures all errors (context access, graph compilation, validation, etc.) to PostHog.
        capture_exception(
            e,
            additional_properties={
                "tag": "max_ai",
                "exception_type": type(e).__name__,
                "conversation_id": str(conversation.id),
            },
        )
        return None, False, {}


class ConversationTaskSerializer(TaskSerializer):
    """The products/tasks Task backing a sandbox conversation.

    Reuses `TaskSerializer` but overrides `latest_run` to be just the latest run's id (not the
    full run object), so the conversation list/retrieve stays cheap — the frontend only needs
    the Task id + latest run id to bootstrap `sandboxStreamLogic.bootstrapRun`. Null for
    LangGraph conversations.
    """

    latest_run = serializers.SerializerMethodField()

    @extend_schema_field(
        serializers.UUIDField(allow_null=True, help_text="Id of the latest TaskRun; null when the task has no runs.")
    )
    def get_latest_run(self, obj: Task) -> str | None:
        # Fast path: the conversation queryset prefetches the task with a `latest_run_id` subquery
        # annotation. Standalone serialization (no annotation) falls back to the `latest_run` property.
        run_id = getattr(obj, "latest_run_id", _UNSET)
        if run_id is _UNSET:
            run = obj.latest_run
            run_id = run.id if run else None
        return str(run_id) if run_id else None


class ConversationMinimalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        # `task` is exposed here (not in `_conversation_fields`) so it stays out of the full
        # serializer's field list, which already appends `task` itself — listing it twice
        # would raise a DRF duplicate-field error.
        fields = [*_conversation_fields, "task"]
        read_only_fields = fields

    user = UserBasicSerializer(read_only=True)
    task = ConversationTaskSerializer(read_only=True, allow_null=True)


class ConversationSerializer(ConversationMinimalSerializer):
    class Meta:
        model = Conversation
        fields = [
            *_conversation_fields,
            "messages",
            "has_unsupported_content",
            "agent_mode",
            "agent_runtime",
            "is_sandbox",
            "pending_approvals",
            "task",
        ]
        read_only_fields = fields

    agent_runtime = serializers.ChoiceField(
        choices=Conversation.AgentRuntime.choices,
        read_only=True,
        help_text=(
            "Runtime that owns this conversation. 'langgraph' conversations return their messages "
            "in the `messages` field; 'sandbox' conversations return an empty `messages` array and "
            "load history from the products/tasks logs endpoint instead."
        ),
    )
    messages = serializers.SerializerMethodField()
    has_unsupported_content = serializers.SerializerMethodField()
    agent_mode = serializers.SerializerMethodField()
    is_sandbox = serializers.SerializerMethodField()
    pending_approvals = serializers.SerializerMethodField()

    def get_messages(self, conversation: Conversation) -> list[dict[str, Any]]:
        # Sandbox conversations don't persist messages Django-side — history lives in S3
        # ACP logs, fetched via the products/tasks `logs/` endpoint.
        if conversation.agent_runtime == Conversation.AgentRuntime.SANDBOX:
            return []

        if conversation.messages_json is not None:
            return conversation.messages_json

        state, _, _ = self._get_cached_state(conversation)
        if state is None:
            return []

        try:
            team = self.context["team"]
            user = self.context["user"]
            artifact_manager = ArtifactManager(team, user)
            enriched_messages = async_to_sync(artifact_manager.aenrich_messages)(list(state.messages))
            messages = [
                message.model_dump() for message in enriched_messages if should_output_assistant_message(message)
            ]
            return messages
        except Exception as e:
            capture_exception(e)
            return []

    def get_has_unsupported_content(self, conversation: Conversation) -> bool:
        _, has_unsupported_content, _ = self._get_cached_state(conversation)
        return has_unsupported_content

    def get_agent_mode(self, conversation: Conversation) -> str | None:
        state, _, _ = self._get_cached_state(conversation)
        if state:
            return state.agent_mode_or_default
        return None

    def get_is_sandbox(self, conversation: Conversation) -> bool:
        return conversation.agent_runtime == Conversation.AgentRuntime.SANDBOX

    def get_pending_approvals(self, conversation: Conversation) -> list[dict[str, Any]]:
        """
        Return pending approval cards as structured data.

        Combines metadata from conversation.approval_decisions with payload from checkpoint
        interrupts (single source of truth for payload data).
        """
        _, _, interrupt_payloads = self._get_cached_state(conversation)

        result: list[dict[str, Any]] = []
        for proposal_id, decision_data in conversation.approval_decisions.items():
            if not isinstance(decision_data, dict):
                continue

            tool_name = decision_data.get("tool_name")
            preview = decision_data.get("preview")
            decision_status = decision_data.get("decision_status")
            if not tool_name or not preview or not decision_status:
                continue

            # Get payload from checkpoint interrupts (single source of truth)
            payload = interrupt_payloads.get(proposal_id, {}).get("payload", {})

            result.append(
                {
                    "proposal_id": proposal_id,
                    "decision_status": decision_status,
                    "tool_name": tool_name,
                    "preview": preview,
                    "payload": payload,
                    "original_tool_call_id": decision_data.get("original_tool_call_id"),
                    "message_id": decision_data.get("message_id"),
                }
            )

        return result

    def _get_cached_state(
        self, conversation: Conversation
    ) -> tuple[AssistantMaxGraphState | None, bool, dict[str, dict[str, Any]]]:
        if not hasattr(self, "_state_cache"):
            self._state_cache: dict[str, tuple[AssistantMaxGraphState | None, bool, dict[str, dict[str, Any]]]] = {}

        cache_key = str(conversation.id)
        if cache_key not in self._state_cache:
            self._state_cache[cache_key] = async_to_sync(self._aget_state)(conversation)

        return self._state_cache[cache_key]

    async def _aget_state(
        self, conversation: Conversation
    ) -> tuple[AssistantMaxGraphState | None, bool, dict[str, dict[str, Any]]]:
        """Async implementation of state fetching with validation error detection.

        Returns:
            Tuple of (state, has_unsupported_content, interrupt_payloads).
            interrupt_payloads is a dict mapping proposal_id to the interrupt value (including payload).
        """
        return await aget_conversation_state(conversation, self.context["team"], self.context["user"])
