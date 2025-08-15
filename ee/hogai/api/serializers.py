from langgraph.graph.state import CompiledStateGraph
import pydantic
from asgiref.sync import async_to_sync
from rest_framework import serializers

from ee.hogai.graph.deep_research.graph import DeepResearchAssistantGraph
from ee.hogai.graph.deep_research.types import DeepResearchState
from ee.hogai.graph.graph import AssistantGraph
from ee.hogai.utils.helpers import should_output_assistant_message
from ee.hogai.utils.types import AssistantState
from ee.models.assistant import Conversation

_conversation_fields = ["id", "status", "title", "created_at", "updated_at", "type"]


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
        graph_class = (
            DeepResearchAssistantGraph if conversation.type == Conversation.Type.DEEP_RESEARCH else AssistantGraph
        )
        graph: CompiledStateGraph = graph_class(team, user).compile_full_graph()  # type: ignore
        snapshot = await graph.aget_state({"configurable": {"thread_id": str(conversation.id)}})
        try:
            state = (
                DeepResearchState.model_validate(snapshot.values)
                if conversation.type == Conversation.Type.DEEP_RESEARCH
                else AssistantState.model_validate(snapshot.values)
            )
            return [message.model_dump() for message in state.messages if should_output_assistant_message(message)]  # type: ignore
        except (pydantic.ValidationError, KeyError):
            return []
