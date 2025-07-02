import json

from pydantic import BaseModel

from ee.hogai.api.serializers import ConversationMinimalSerializer
from ee.hogai.utils.types import AssistantOutput
from ee.models.assistant import Conversation
from posthog.schema import AssistantEventType, AssistantGenerationStatusEvent


class SSESerializer:
    def dumps(self, event: AssistantOutput) -> str:
        if event[0] == AssistantEventType.MESSAGE:
            return self._serialize_message(event[1])
        elif event[0] == AssistantEventType.CONVERSATION:
            return self._serialize_conversation(event[1])
        else:
            raise ValueError(f"Unknown event type: {event[0]}")

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
