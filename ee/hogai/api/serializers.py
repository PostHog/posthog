import pydantic
from asgiref.sync import async_to_sync
from langgraph.graph.state import CompiledStateGraph
from rest_framework import serializers

from ee.hogai.graph.deep_research.graph import DeepResearchAssistantGraph
from ee.hogai.graph.deep_research.types import DeepResearchState
from ee.hogai.graph.graph import AssistantGraph
from ee.hogai.utils.helpers import should_output_assistant_message
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.composed import AssistantMaxGraphState
from ee.models.assistant import Conversation

_conversation_fields = ["id", "status", "title", "created_at", "updated_at", "type"]

MaxGraphType = DeepResearchAssistantGraph | AssistantGraph

CONVERSATION_TYPE_MAP: dict[Conversation.Type, tuple[type[MaxGraphType], type[AssistantMaxGraphState]]] = {
    Conversation.Type.DEEP_RESEARCH: (DeepResearchAssistantGraph, DeepResearchState),
    Conversation.Type.ASSISTANT: (AssistantGraph, AssistantState),
    Conversation.Type.TOOL_CALL: (AssistantGraph, AssistantState),
}


class ConversationMinimalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = _conversation_fields
        read_only_fields = fields


class ConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = [*_conversation_fields, "messages"]
        read_only_fields = fields

    messages = serializers.SerializerMethodField()

    @async_to_sync
    async def get_messages(self, conversation: Conversation):
        team = self.context["team"]
        user = self.context["user"]
        graph_class, state_class = CONVERSATION_TYPE_MAP[conversation.type]  # type: ignore[index]
        graph: CompiledStateGraph = graph_class(team, user).compile_full_graph()
        snapshot = await graph.aget_state({"configurable": {"thread_id": str(conversation.id)}})
        try:
            state = state_class.model_validate(snapshot.values)
            return [message.model_dump() for message in state.messages if should_output_assistant_message(message)]
        except (pydantic.ValidationError, KeyError):
            return []
