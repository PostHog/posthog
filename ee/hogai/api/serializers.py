from typing import Any

import pydantic
from asgiref.sync import async_to_sync, sync_to_async
from drf_spectacular.utils import extend_schema_field
from langgraph.graph.state import CompiledStateGraph
from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.shared import UserBasicSerializer
from posthog.exceptions_capture import capture_exception

from products.posthog_ai.backend.models.assistant import Conversation
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.contracts import TaskDetailDTO, TaskRunDetailDTO, TaskUserBasicInfo
from products.tasks.backend.facade.run_config import PUBLIC_REASONING_EFFORTS, LLMProvider, RuntimeAdapter

from ee.hogai.artifacts.manager import ArtifactManager
from ee.hogai.chat_agent import AssistantGraph
from ee.hogai.research_agent.graph import ResearchAgentGraph
from ee.hogai.tool import PENDING_APPROVAL_STATUS
from ee.hogai.utils.helpers import should_output_assistant_message
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.composed import AssistantMaxGraphState

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

    Returns (state, has_unsupported_content, interrupt_payloads). `state` is None for born-sandbox
    conversations (no checkpoint) and on any read/validation error — errors degrade gracefully
    and are captured rather than raised so a bad checkpoint can't 500 a conversation load.
    """
    # Born-sandbox conversations have no LangGraph checkpoint — skip the graph compile entirely.
    # A CONVERTED conversation (now sandbox, but kept its legacy checkpoint) falls through so its
    # legacy thread still renders above the "history was converted" divider.
    if conversation.agent_runtime == Conversation.AgentRuntime.SANDBOX:
        has_checkpoint = await sync_to_async(conversation.checkpoints.exists)()
        if not has_checkpoint:
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


class TaskUserBasicInfoSerializer(DataclassSerializer):
    """Response shape for a task creator, mirroring core ``UserBasicSerializer`` output."""

    class Meta:
        dataclass = TaskUserBasicInfo


class TaskRunArtifactResponseSerializer(serializers.Serializer):
    id = serializers.CharField(required=False, help_text="Stable identifier for the artifact within this run")
    name = serializers.CharField(help_text="Artifact file name")
    type = serializers.CharField(help_text="Artifact classification, such as plan or output")
    source = serializers.CharField(  # type: ignore[assignment]  # field literally named `source`; shadows base `Field.source`
        required=False,
        allow_blank=True,
        help_text="Source of the artifact, such as agent_output or user_attachment",
    )
    size = serializers.IntegerField(required=False, help_text="Artifact size in bytes")
    content_type = serializers.CharField(required=False, allow_blank=True, help_text="Optional MIME type")
    storage_path = serializers.CharField(help_text="S3 object key for the artifact")
    uploaded_at = serializers.CharField(help_text="Timestamp when the artifact was uploaded")


class TaskRunDetailSerializer(DataclassSerializer):
    """Detail response for the latest task run when a caller includes it."""

    task = serializers.UUIDField(help_text="Parent task id this run belongs to.")
    log_url = serializers.URLField(allow_null=True, required=False, help_text="Presigned S3 URL for log access.")
    artifacts = TaskRunArtifactResponseSerializer(many=True, read_only=True)
    runtime_adapter = serializers.ChoiceField(
        choices=[adapter.value for adapter in RuntimeAdapter],
        allow_null=True,
        required=False,
        help_text="Configured runtime adapter for this run, such as 'claude' or 'codex'.",
    )
    provider = serializers.ChoiceField(
        choices=[provider.value for provider in LLMProvider],
        allow_null=True,
        required=False,
        help_text="Configured LLM provider for this run, such as 'anthropic' or 'openai'.",
    )
    model = serializers.CharField(
        allow_null=True, required=False, help_text="Configured LLM model identifier for this run."
    )
    reasoning_effort = serializers.ChoiceField(
        choices=[effort.value for effort in PUBLIC_REASONING_EFFORTS],
        allow_null=True,
        required=False,
        help_text="Configured reasoning effort for this run when the selected model supports it.",
    )

    class Meta:
        dataclass = TaskRunDetailDTO
        fields = [
            "id",
            "task",
            "stage",
            "branch",
            "status",
            "environment",
            "runtime_adapter",
            "provider",
            "model",
            "reasoning_effort",
            "log_url",
            "error_message",
            "output",
            "state",
            "artifacts",
            "created_at",
            "updated_at",
            "completed_at",
        ]


class TaskSerializer(DataclassSerializer):
    """Local serializer for the products/tasks task DTO exposed in conversation responses."""

    latest_run = TaskRunDetailSerializer(allow_null=True, required=False, help_text="Latest run details for this task")
    created_by = TaskUserBasicInfoSerializer(allow_null=True, required=False)

    class Meta:
        dataclass = TaskDetailDTO
        fields = [
            "id",
            "task_number",
            "slug",
            "title",
            "title_manually_set",
            "description",
            "origin_product",
            "repository",
            "github_integration",
            "github_user_integration",
            "signal_report",
            "json_schema",
            "internal",
            "archived",
            "archived_at",
            "latest_run",
            "created_at",
            "updated_at",
            "created_by",
            "ci_prompt",
        ]


class ConversationTaskSerializer(TaskSerializer):
    """Conversation envelope variant: ``latest_run`` is just the latest run's id, not the nested
    run detail. The frontend only needs the id to reconnect to sandbox logs, and emitting the id
    avoids presigning a log URL per conversation.

    Read access here follows the conversation (the share-by-link unit), not per-creator task
    visibility — write/send stays creator-gated. See ``tasks_facade.get_conversation_task_dtos``."""

    latest_run = serializers.UUIDField(  # type: ignore[assignment]  # intentional narrowing of the base nested-run field to its id
        source="latest_run_id",
        allow_null=True,
        read_only=True,
        help_text="Id of the latest TaskRun; null when the task has no runs.",
    )


class ConversationMinimalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        # `task` is exposed here (not in `_conversation_fields`) so it stays out of the full
        # serializer's field list, which already appends `task` itself — listing it twice
        # would raise a DRF duplicate-field error.
        fields = [*_conversation_fields, "task"]
        read_only_fields = fields

    user = UserBasicSerializer(read_only=True)
    task = serializers.SerializerMethodField()

    @extend_schema_field(ConversationTaskSerializer(allow_null=True))
    def get_task(self, conversation: Conversation) -> dict[str, Any] | None:
        if conversation.task_id is None:
            return None

        task_dtos = self.context.get("conversation_task_dtos_by_id")
        task_dto: TaskDetailDTO | None = (
            task_dtos.get(str(conversation.task_id)) if isinstance(task_dtos, dict) else None
        )
        if task_dto is None:
            team = self.context["team"]
            task_dto = tasks_facade.get_conversation_task_dtos([conversation.task_id], team.id).get(
                conversation.task_id
            )
        if task_dto is None:
            return None
        return ConversationTaskSerializer(task_dto).data


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
            "in the `messages` field; born-'sandbox' conversations return an empty `messages` array "
            "and load history from the products/tasks logs endpoint. A converted conversation is "
            "'sandbox' but still returns its legacy thread in `messages`."
        ),
    )
    messages = serializers.SerializerMethodField()
    has_unsupported_content = serializers.SerializerMethodField()
    agent_mode = serializers.SerializerMethodField()
    is_sandbox = serializers.SerializerMethodField()
    pending_approvals = serializers.SerializerMethodField()

    def get_messages(self, conversation: Conversation) -> list[dict[str, Any]]:
        # Born-sandbox conversations have no checkpoint — their history lives in S3 ACP logs
        # (fetched via the products/tasks `logs/` endpoint), so `_get_cached_state` returns None and
        # messages are []; the cached `messages_json` is intentionally ignored on this path. A
        # CONVERTED conversation keeps its legacy checkpoint, so its full legacy thread is returned
        # (rendered above the conversion divider). LangGraph conversations use the cached
        # `messages_json` when present, else compile + replay the checkpoint.
        if conversation.agent_runtime == Conversation.AgentRuntime.SANDBOX:
            state, _, _ = self._get_cached_state(conversation)
            return self._render_state_messages(state)

        if conversation.messages_json is not None:
            return conversation.messages_json

        state, _, _ = self._get_cached_state(conversation)
        return self._render_state_messages(state)

    def _render_state_messages(self, state: AssistantMaxGraphState | None) -> list[dict[str, Any]]:
        if state is None:
            return []
        try:
            team = self.context["team"]
            user = self.context["user"]
            artifact_manager = ArtifactManager(team, user)
            enriched_messages = async_to_sync(artifact_manager.aenrich_messages)(list(state.messages))
            return [message.model_dump() for message in enriched_messages if should_output_assistant_message(message)]
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
