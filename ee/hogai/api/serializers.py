import pydantic
from asgiref.sync import async_to_sync
from langgraph.graph.state import CompiledStateGraph
from rest_framework import serializers

from ee.hogai.utils.helpers import should_output_assistant_message
from ee.hogai.utils.types import AssistantState
from ee.models.assistant import Conversation
from posthog.api.shared import UserBasicSerializer

_conversation_fields = ["id", "user", "status", "title", "created_at", "updated_at"]


class ConversationMinimalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = _conversation_fields
        read_only_fields = fields

    user = UserBasicSerializer(read_only=True)


class ConversationSerializer(ConversationMinimalSerializer):
    class Meta:
        model = Conversation
        fields = [*_conversation_fields, "messages"]
        read_only_fields = fields

    messages = serializers.SerializerMethodField()

    @async_to_sync
    async def get_messages(self, conversation: Conversation):
        graph: CompiledStateGraph = self.context["assistant_graph"]
        snapshot = await graph.aget_state({"configurable": {"thread_id": str(conversation.id)}})
        try:
            state = AssistantState.model_validate(snapshot.values)
            return [message.model_dump() for message in state.messages if should_output_assistant_message(message)]
        except (pydantic.ValidationError, KeyError):
            return []
