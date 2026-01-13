from typing import Any

import pydantic
from asgiref.sync import async_to_sync
from langgraph.graph.state import CompiledStateGraph
from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer
from posthog.exceptions_capture import capture_exception

from ee.hogai.artifacts.manager import ArtifactManager
from ee.hogai.chat_agent import AssistantGraph
from ee.hogai.tool import PENDING_APPROVAL_STATUS
from ee.hogai.utils.helpers import should_output_assistant_message
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.composed import AssistantMaxGraphState
from ee.models.assistant import Conversation

_conversation_fields = [
    "id",
    "status",
    "title",
    "user",
    "created_at",
    "updated_at",
    "type",
    "is_internal",
    "slack_thread_key",
    "slack_workspace_domain",
]


CONVERSATION_TYPE_MAP: dict[Conversation.Type, tuple[type[AssistantGraph], type[AssistantMaxGraphState]]] = {
    Conversation.Type.ASSISTANT: (AssistantGraph, AssistantState),
    Conversation.Type.TOOL_CALL: (AssistantGraph, AssistantState),
    Conversation.Type.SLACK: (AssistantGraph, AssistantState),
}


class ConversationMinimalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = _conversation_fields
        read_only_fields = fields

    user = UserBasicSerializer(read_only=True)


class ConversationSerializer(ConversationMinimalSerializer):
    class Meta:
        model = Conversation
        fields = [*_conversation_fields, "messages", "has_unsupported_content", "agent_mode", "pending_approvals"]
        read_only_fields = fields

    messages = serializers.SerializerMethodField()
    has_unsupported_content = serializers.SerializerMethodField()
    agent_mode = serializers.SerializerMethodField()
    pending_approvals = serializers.SerializerMethodField()

    def get_messages(self, conversation: Conversation) -> list[dict[str, Any]]:
        state, _, _ = self._get_cached_state(conversation)
        if state is None:
            return []

        team = self.context["team"]
        user = self.context["user"]
        artifact_manager = ArtifactManager(team, user)
        enriched_messages = async_to_sync(artifact_manager.aenrich_messages)(list(state.messages))
        return [message.model_dump() for message in enriched_messages if should_output_assistant_message(message)]

    def get_has_unsupported_content(self, conversation: Conversation) -> bool:
        _, has_unsupported_content, _ = self._get_cached_state(conversation)
        return has_unsupported_content

    def get_agent_mode(self, conversation: Conversation) -> str | None:
        state, _, _ = self._get_cached_state(conversation)
        if state:
            return state.agent_mode_or_default
        return None

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
        try:
            team = self.context["team"]
            user = self.context["user"]
            graph_class, state_class = CONVERSATION_TYPE_MAP[conversation.type]  # type: ignore[index]
            graph: CompiledStateGraph = graph_class(team, user).compile_full_graph()
            snapshot = await graph.aget_state(
                {"configurable": {"thread_id": str(conversation.id), "checkpoint_ns": ""}}
            )
            state = state_class.model_validate(snapshot.values)

            # Extract interrupt payloads from pending tasks
            # This is the single source of truth for payload data
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
            # Broad exception handler to gracefully degrade UI instead of 500s
            # Captures all errors (context access, graph compilation, validation, etc.) to PostHog
            capture_exception(
                e,
                additional_properties={
                    "tag": "max_ai",
                    "exception_type": type(e).__name__,
                    "conversation_id": str(conversation.id),
                },
            )
            return None, False, {}
