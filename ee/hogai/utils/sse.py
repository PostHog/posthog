import json
from typing import cast

from pydantic import BaseModel

from posthog.schema import AssistantEventType, AssistantGenerationStatusEvent

from ee.hogai.api.serializers import ConversationMinimalSerializer
from ee.hogai.utils.types import AssistantMessageUnion, AssistantOutput
from ee.models.assistant import Conversation


class AssistantSSESerializer:
    def dumps(self, event: AssistantOutput) -> str:
        event_type, event_data = event
        if event_type == AssistantEventType.MESSAGE:
            return self._serialize_message(cast(AssistantMessageUnion, event_data))
        elif event_type == AssistantEventType.CONVERSATION:
            return self._serialize_conversation(cast(Conversation, event_data))
        else:
            raise ValueError(f"Unknown event type: {event_type}")

    def _serialize_message(self, message: BaseModel) -> str:
        output = ""
        if isinstance(message, AssistantGenerationStatusEvent):
            output += f"event: {AssistantEventType.STATUS}\n"
        else:
            output += f"event: {AssistantEventType.MESSAGE}\n"
        return output + f"data: {message.model_dump_json(exclude_none=True, exclude={'tool_calls'})}\n\n"

    def _serialize_conversation(self, conversation: Conversation) -> str:
        output = f"event: {AssistantEventType.CONVERSATION}\n"
        json_conversation = json.dumps(ConversationMinimalSerializer(conversation).data)
        output += f"data: {json_conversation}\n\n"
        return output
