import json
from typing import cast

from posthog.schema import AssistantEventType, AssistantGenerationStatusEvent, AssistantUpdateEvent

from ee.hogai.api.serializers import ConversationMinimalSerializer
from ee.hogai.utils.types.base import AssistantMessageUnion, AssistantResultUnion
from ee.models.assistant import Conversation


class AssistantSSESerializer:
    def dumps(self, event: AssistantResultUnion | Conversation) -> str:
        if isinstance(event, AssistantUpdateEvent):
            return self._serialize_update(event)
        elif isinstance(event, AssistantGenerationStatusEvent):
            return self._serialize_status(event)
        elif isinstance(event, Conversation):
            return self._serialize_conversation(event)
        else:
            return self._serialize_message(cast(AssistantMessageUnion, event))

    def _serialize_message(self, message: AssistantMessageUnion) -> str:
        output = f"event: {AssistantEventType.MESSAGE}\n"
        output += f"data: {message.model_dump_json(exclude_none=True)}\n\n"
        return output

    def _serialize_status(self, status: AssistantGenerationStatusEvent) -> str:
        output = f"event: {AssistantEventType.STATUS}\n"
        output += f"data: {status.model_dump_json(exclude_none=True)}\n\n"
        return output

    def _serialize_update(self, update: AssistantUpdateEvent) -> str:
        output = f"event: {AssistantEventType.UPDATE}\n"
        output += f"data: {update.model_dump_json(exclude_none=True)}\n\n"
        return output

    def _serialize_conversation(self, conversation: Conversation) -> str:
        output = f"event: {AssistantEventType.CONVERSATION}\n"
        json_conversation = json.dumps(ConversationMinimalSerializer(conversation).data)
        output += f"data: {json_conversation}\n\n"
        return output
