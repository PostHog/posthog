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

_conversation_fields = ["id", "status", "title", "user", "created_at", "updated_at", "type"]


CONVERSATION_TYPE_MAP: dict[Conversation.Type, tuple[type[AssistantGraph], type[AssistantMaxGraphState]]] = {
    Conversation.Type.ASSISTANT: (AssistantGraph, AssistantState),
    Conversation.Type.TOOL_CALL: (AssistantGraph, AssistantState),
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
        fields = [*_conversation_fields, "messages", "has_unsupported_content"]
        read_only_fields = fields

    messages = serializers.SerializerMethodField()
    has_unsupported_content = serializers.SerializerMethodField()

    def _get_messages_with_flag(self, conversation: Conversation) -> tuple[list[dict[str, Any]], bool]:
        """
        Fetches messages for a conversation and determines if content is unsupported (due to validation errors)
        Results are cached per conversation to avoid redundant expensive operations, since expensive operations
        (graph compilation, state retrieval, validation) happen for every conversation in the list.
        DRF would otherwise perform these operations for every conversation in the list.

        Returns:
            Tuple of (messages, has_unsupported_content) where:
            - messages: List of serialized messages (empty list on any error)
            - has_unsupported_content: True only if we have encountered Pydantic validation errors
        """
        if not hasattr(self, "_cache"):
            self._cache: dict[str, tuple[list[dict[str, Any]], bool]] = {}

        cache_key = str(conversation.id)
        if cache_key in self._cache:
            return self._cache[cache_key]

        result = async_to_sync(self._aget_messages_with_flag)(conversation)
        self._cache[cache_key] = result
        return result

    async def _aget_messages_with_flag(self, conversation: Conversation) -> tuple[list[dict[str, Any]], bool]:
        """Async implementation of message fetching with validation error detection."""
        try:
            team = self.context["team"]
            user = self.context["user"]
            graph_class, state_class = CONVERSATION_TYPE_MAP[conversation.type]  # type: ignore[index]
            graph: CompiledStateGraph = graph_class(team, user).compile_full_graph()
            snapshot = await graph.aget_state(
                {"configurable": {"thread_id": str(conversation.id), "checkpoint_ns": ""}}
            )
            state = state_class.model_validate(snapshot.values)
            messages = list(state.messages)
            artifact_manager = ArtifactManager(team, user)
            enriched_messages = await artifact_manager.aenrich_messages(messages)
            return [m.model_dump() for m in enriched_messages if should_output_assistant_message(m)], False

        except pydantic.ValidationError as e:
            capture_exception(
                e,
                additional_properties={
                    "tag": "max_ai",
                    "exception_type": "ValidationError",
                    "conversation_id": str(conversation.id),
                },
            )
            return [], True
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
            return [], False

    def get_messages(self, conversation: Conversation) -> list[dict[str, Any]]:
        messages, _ = self._get_messages_with_flag(conversation)
        return messages

    def get_has_unsupported_content(self, conversation: Conversation) -> bool:
        _, has_unsupported_content = self._get_messages_with_flag(conversation)
        return has_unsupported_content
