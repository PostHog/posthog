import json
import time
import asyncio
from collections.abc import Callable
from typing import TypeVar, cast

from django.conf import settings

from prometheus_client import Histogram

from posthog.schema import AssistantEventType, AssistantGenerationStatusEvent, AssistantUpdateEvent, SubagentUpdateEvent

from posthog.sync import database_sync_to_async

from products.posthog_ai.backend.models.assistant import Conversation

from ee.hogai.api.serializers import ConversationMinimalSerializer
from ee.hogai.utils.types import AssistantMessageUnion, AssistantOutput

T = TypeVar("T")

SSE_SERIALIZE_LATENCY_HISTOGRAM = Histogram(
    "posthog_ai_sse_serialize_latency_seconds",
    "Time spent serializing an SSE event payload (model_dump_json), labeled by whether it ran off the event loop",
    ["offloaded"],
    buckets=[0.0005, 0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, float("inf")],
)


class AssistantSSESerializer:
    async def dumps(self, event: AssistantOutput) -> str:
        event_type, event_data = event
        if event_type == AssistantEventType.MESSAGE:
            return await self._offload(self._serialize_message, cast(AssistantMessageUnion, event_data))
        elif event_type == AssistantEventType.CONVERSATION:
            return await self._serialize_conversation(cast(Conversation, event_data))
        elif event_type == AssistantEventType.STATUS:
            return await self._offload(self._serialize_status, cast(AssistantGenerationStatusEvent, event_data))
        elif event_type == AssistantEventType.UPDATE:
            return await self._offload(
                self._serialize_update, cast(AssistantUpdateEvent | SubagentUpdateEvent, event_data)
            )
        else:
            raise ValueError(f"Unknown event type: {event_type}")

    async def _offload(self, fn: Callable[[T], str], payload: T) -> str:
        """Run a CPU-bound serializer, optionally on a worker thread so the ASGI event loop stays free.

        Ordering is preserved: callers await the result before yielding the next chunk.
        """
        offload = settings.MAX_AI_STREAM_OFFLOAD_SERIALIZATION
        start = time.perf_counter()
        try:
            if offload:
                return await asyncio.to_thread(fn, payload)
            return fn(payload)
        finally:
            SSE_SERIALIZE_LATENCY_HISTOGRAM.labels(offloaded="true" if offload else "false").observe(
                time.perf_counter() - start
            )

    def _serialize_message(self, message: AssistantMessageUnion) -> str:
        output = f"event: {AssistantEventType.MESSAGE}\n"
        output += f"data: {message.model_dump_json(exclude_none=True)}\n\n"
        return output

    def _serialize_status(self, status: AssistantGenerationStatusEvent) -> str:
        output = f"event: {AssistantEventType.STATUS}\n"
        output += f"data: {status.model_dump_json(exclude_none=True)}\n\n"
        return output

    def _serialize_update(self, update: AssistantUpdateEvent | SubagentUpdateEvent) -> str:
        output = f"event: {AssistantEventType.UPDATE}\n"
        output += f"data: {update.model_dump_json(exclude_none=True)}\n\n"
        return output

    # `_serialize_conversation` needs to be async, as some serialization CAN involve sneaky sync ORM queries. We can't guarantee it won't.
    # In particular, serialization Conversation can involve fetching conversation.user from DB sync. This shouldn't
    # be needed, because we SHOULD be doing Conversation.objects.select_related("user"), but async here is a cheap way to safe.
    @database_sync_to_async
    def _serialize_conversation(self, conversation: Conversation) -> str:
        output = f"event: {AssistantEventType.CONVERSATION}\n"
        json_conversation = json.dumps(ConversationMinimalSerializer(conversation).data)
        output += f"data: {json_conversation}\n\n"
        return output
