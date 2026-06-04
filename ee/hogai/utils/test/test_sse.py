import asyncio
from typing import cast

import pytest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.schema import (
    AssistantEventType,
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
    AssistantMessage,
    AssistantUpdateEvent,
)

from ee.hogai.utils.sse import AssistantSSESerializer
from ee.hogai.utils.types import AssistantOutput


# Pure-CPU serializer paths (MESSAGE/STATUS/UPDATE) — no DB needed, so no Django TestCase base.
class TestAssistantSSESerializer:
    def setup_method(self):
        self.serializer = AssistantSSESerializer()

    def _message_event(self) -> AssistantOutput:
        return cast(AssistantOutput, (AssistantEventType.MESSAGE, AssistantMessage(content="hello world")))

    @parameterized.expand([("offload_on", True), ("offload_off", False)])
    @pytest.mark.asyncio
    async def test_message_serialization_identical_regardless_of_offload(self, _name: str, offload: bool):
        message = AssistantMessage(content="hello world")
        event = cast(AssistantOutput, (AssistantEventType.MESSAGE, message))

        with override_settings(MAX_AI_STREAM_OFFLOAD_SERIALIZATION=offload):
            result = await self.serializer.dumps(event)

        assert result == f"event: {AssistantEventType.MESSAGE}\ndata: {message.model_dump_json(exclude_none=True)}\n\n"

    @parameterized.expand(
        [
            (
                "status",
                lambda: (
                    AssistantEventType.STATUS,
                    AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.GENERATION_ERROR),
                ),
            ),
            (
                "update",
                lambda: (
                    AssistantEventType.UPDATE,
                    AssistantUpdateEvent(content="thinking", id="msg-1", tool_call_id="tc-1"),
                ),
            ),
        ]
    )
    @pytest.mark.asyncio
    async def test_other_event_types_serialize_with_offload_enabled(self, _name, build_event):
        event_type, payload = build_event()
        event = cast(AssistantOutput, (event_type, payload))

        with override_settings(MAX_AI_STREAM_OFFLOAD_SERIALIZATION=True):
            result = await self.serializer.dumps(event)

        assert result == f"event: {event_type}\ndata: {payload.model_dump_json(exclude_none=True)}\n\n"

    @pytest.mark.asyncio
    async def test_offload_routes_serialization_through_thread_pool(self):
        with override_settings(MAX_AI_STREAM_OFFLOAD_SERIALIZATION=True):
            with patch("ee.hogai.utils.aio.asyncio.to_thread", wraps=asyncio.to_thread) as mock_to_thread:
                result = await self.serializer.dumps(self._message_event())

        mock_to_thread.assert_called_once()
        assert result.startswith(f"event: {AssistantEventType.MESSAGE}\n")

    @pytest.mark.asyncio
    async def test_no_offload_keeps_serialization_on_the_loop(self):
        with override_settings(MAX_AI_STREAM_OFFLOAD_SERIALIZATION=False):
            with patch("ee.hogai.utils.aio.asyncio.to_thread", wraps=asyncio.to_thread) as mock_to_thread:
                await self.serializer.dumps(self._message_event())

        mock_to_thread.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_event_type_raises(self):
        with pytest.raises(ValueError, match="Unknown event type"):
            await self.serializer.dumps(cast(AssistantOutput, ("NOT_AN_EVENT", AssistantMessage(content="x"))))

    @staticmethod
    def _serialize_count(offloaded: str) -> float:
        return (
            REGISTRY.get_sample_value("posthog_ai_sse_serialize_latency_seconds_count", {"offloaded": offloaded}) or 0.0
        )

    @parameterized.expand([("offload_on", True, "true"), ("offload_off", False, "false")])
    @pytest.mark.asyncio
    async def test_latency_histogram_records_with_offloaded_label(self, _name: str, offload: bool, label: str):
        before = self._serialize_count(label)

        with override_settings(MAX_AI_STREAM_OFFLOAD_SERIALIZATION=offload):
            await self.serializer.dumps(self._message_event())

        assert self._serialize_count(label) == before + 1

    @parameterized.expand([("offload_on", True, "true"), ("offload_off", False, "false")])
    @pytest.mark.asyncio
    async def test_serializer_failure_propagates_and_is_still_timed(self, _name: str, offload: bool, label: str):
        # Timing is observed in a finally, so a failed serialization must still be measured and re-raised.
        before = self._serialize_count(label)

        with patch.object(self.serializer, "_serialize_message", side_effect=ValueError("boom")):
            with override_settings(MAX_AI_STREAM_OFFLOAD_SERIALIZATION=offload):
                with pytest.raises(ValueError, match="boom"):
                    await self.serializer.dumps(self._message_event())

        assert self._serialize_count(label) == before + 1
