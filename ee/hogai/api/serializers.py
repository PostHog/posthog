from typing import Any

import pydantic
from asgiref.sync import async_to_sync
from langgraph.graph.state import CompiledStateGraph
from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer
from posthog.exceptions_capture import capture_exception

from ee.hogai.artifacts.manager import ArtifactManager
from ee.hogai.chat_agent import AssistantGraph
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
        fields = [*_conversation_fields, "messages", "has_unsupported_content", "agent_mode", "approval_decisions"]
        read_only_fields = fields

    messages = serializers.SerializerMethodField()
    has_unsupported_content = serializers.SerializerMethodField()
    agent_mode = serializers.SerializerMethodField()
    approval_decisions = serializers.JSONField(read_only=True)

    def get_messages(self, conversation: Conversation) -> list[dict[str, Any]]:
        state, _ = self._get_cached_state(conversation)
        if state is None:
            return []

        team = self.context["team"]
        user = self.context["user"]
        artifact_manager = ArtifactManager(team, user)
        enriched_messages = async_to_sync(artifact_manager.aenrich_messages)(list(state.messages))
        messages = [message.model_dump() for message in enriched_messages if should_output_assistant_message(message)]
        return messages

    def get_has_unsupported_content(self, conversation: Conversation) -> bool:
        _, has_unsupported_content = self._get_cached_state(conversation)
        return has_unsupported_content

    def get_agent_mode(self, conversation: Conversation) -> str | None:
        state, _ = self._get_cached_state(conversation)
        if state:
            return state.agent_mode_or_default
        return None

    def _get_cached_state(self, conversation: Conversation) -> tuple[AssistantMaxGraphState | None, bool]:
        if not hasattr(self, "_state_cache"):
            self._state_cache: dict[str, tuple[AssistantMaxGraphState | None, bool]] = {}

        cache_key = str(conversation.id)
        if cache_key not in self._state_cache:
            self._state_cache[cache_key] = async_to_sync(self._aget_state)(conversation)

        return self._state_cache[cache_key]

    async def _aget_state(self, conversation: Conversation) -> tuple[AssistantMaxGraphState | None, bool]:
        """Async implementation of state fetching with validation error detection."""
        try:
            team = self.context["team"]
            user = self.context["user"]
            graph_class, state_class = CONVERSATION_TYPE_MAP[conversation.type]  # type: ignore[index]
            graph: CompiledStateGraph = graph_class(team, user).compile_full_graph()
            snapshot = await graph.aget_state(
                {"configurable": {"thread_id": str(conversation.id), "checkpoint_ns": ""}}
            )
            state = state_class.model_validate(snapshot.values)
            return state, False
        except pydantic.ValidationError as e:
            capture_exception(
                e,
                additional_properties={
                    "tag": "max_ai",
                    "exception_type": "ValidationError",
                    "conversation_id": str(conversation.id),
                },
            )
            return None, True
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
            return None, False
