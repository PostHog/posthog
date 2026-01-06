from typing import Any

import pydantic
from asgiref.sync import async_to_sync
from langgraph.graph.state import CompiledStateGraph
from rest_framework import serializers

from posthog.schema import AssistantToolCallMessage

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

        # Reconstruct approval card messages from approval_decisions
        messages = self._inject_approval_cards(messages, conversation.approval_decisions)

        return messages

    def get_has_unsupported_content(self, conversation: Conversation) -> bool:
        _, has_unsupported_content = self._get_cached_state(conversation)
        return has_unsupported_content

    def get_agent_mode(self, conversation: Conversation) -> str | None:
        state, _ = self._get_cached_state(conversation)
        if state:
            return state.agent_mode_or_default
        return None

    def _inject_approval_cards(
        self, messages: list[dict[str, Any]], approval_decisions: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """
        Reconstruct and inject approval card messages from approval_decisions.

        Since these cannot be stored in LangGraph state (it would break the interrupt
        checkpoint), we store their metadata in conversation.approval_decisions and reconstruct
        them here when loading the conversation.
        """
        if not approval_decisions:
            return messages

        # Build a map of tool_name -> approval card data for cards we need to inject
        cards_to_inject: list[dict[str, Any]] = []
        for proposal_id, decision_data in approval_decisions.items():
            if not isinstance(decision_data, dict):
                continue

            tool_name = decision_data.get("tool_name")
            preview = decision_data.get("preview")
            message_id = decision_data.get("message_id")
            payload = decision_data.get("payload", {})
            original_tool_call_id = decision_data.get("original_tool_call_id")

            if not tool_name or not preview:
                continue

            # Create the approval card message with format expected by FE
            card_message = AssistantToolCallMessage(
                content="",
                ui_payload={
                    tool_name: {
                        "status": PENDING_APPROVAL_STATUS,
                        "tool_name": tool_name,
                        "preview": preview,
                        "proposal_id": proposal_id,
                        "payload": payload,
                    }
                },
                id=message_id,
                tool_call_id=proposal_id,
            )
            cards_to_inject.append(
                {
                    "card": card_message.model_dump(),
                    "tool_name": tool_name,
                    "message_id": message_id,
                    "original_tool_call_id": original_tool_call_id,
                }
            )

        if not cards_to_inject:
            return messages

        result: list[dict[str, Any]] = []
        injected_ids: set[str] = set()

        for msg in messages:
            result.append(msg)

            # Check if this is an AssistantMessage with tool_calls
            if msg.get("type") == "ai" and msg.get("tool_calls"):
                tool_calls = msg.get("tool_calls", [])
                tool_call_ids_in_msg = {tc.get("id") for tc in tool_calls if tc.get("id")}
                # tool_names_in_msg = {tc.get("name") for tc in tool_calls if tc.get("name")}

                # Inject any approval cards that match tool_calls in this message
                for card_info in cards_to_inject:
                    card_id = card_info["message_id"]
                    if card_id and card_id in injected_ids:
                        continue

                    original_tool_call_id = card_info.get("original_tool_call_id")
                    if original_tool_call_id and original_tool_call_id in tool_call_ids_in_msg:
                        result.append(card_info["card"])
                        if card_id:
                            injected_ids.add(card_id)
                    # elif not original_tool_call_id and card_info["tool_name"] in tool_names_in_msg:
                    #     # Legacy fallback: match by tool_name only if no original_tool_call_id
                    #     result.append(card_info["card"])
                    #     if card_id:
                    #         injected_ids.add(card_id)

        # If any cards weren't injected (e.g., no matching tool call found), append at end
        for card_info in cards_to_inject:
            card_id = card_info["message_id"]
            if card_id and card_id not in injected_ids:
                result.append(card_info["card"])

        return result

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
