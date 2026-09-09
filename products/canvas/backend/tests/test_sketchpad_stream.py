import json
import asyncio

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog import redis

from products.canvas.backend.sketchpad_presence import (
    PRESENCE_STREAM_KEY_PATTERN,
    PRESENCE_TTL_SECONDS,
    publish_presence,
)
from products.canvas.backend.sketchpad_stream import OPS_STREAM_KEY_PATTERN, publish_ops, stream_sketchpad_sse


def op_event(seq: int) -> dict:
    return {
        "seq": seq,
        "op_id": f"op-{seq}",
        "actor": {"kind": "user", "user_id": 7, "user_name": "Grace Hopper", "task_id": None},
        "created_at": "2026-09-03T10:00:00+00:00",
        "op": {"type": "bring_to_front", "id": "kpi"},
    }


def first_frame(team_id: int, sketchpad_id: str, last_event_id: str | None) -> bytes:
    async def read() -> bytes:
        frames = stream_sketchpad_sse(
            team_id, sketchpad_id, can_read=AsyncMock(return_value=True), last_event_id=last_event_id
        )
        try:
            return await anext(frames)
        finally:
            await frames.aclose()

    return asyncio.run(read())


class TestSketchpadStreamAccess(SimpleTestCase):
    @parameterized.expand(
        [("presence", 20, 100, 0.005, 7, 0.5), ("presence", 100, 500, 0.001, 22, 0.5), ("op", 1, 96, 0.0, 4, 0.0)]
    )
    def test_batches_small_events_and_drains_full_batches(
        self, kind: str, writers: int, event_count: int, interval: float, max_checks: int, max_time: float
    ) -> None:
        now = 0.0
        position = 0
        client = AsyncMock()
        client.xrevrange.return_value = []
        can_read = AsyncMock(return_value=True)
        key = (PRESENCE_STREAM_KEY_PATTERN if kind == "presence" else OPS_STREAM_KEY_PATTERN).format(
            team_id=1, sketchpad_id="sketchpad"
        )

        async def read_batch(
            _streams: object, *, block: int, count: int
        ) -> list[tuple[bytes, list[tuple[bytes, dict[bytes, bytes]]]]]:
            nonlocal now, position
            now = max(now, position * interval)
            entries: list[tuple[bytes, dict[bytes, bytes]]] = []
            while position < event_count and len(entries) < count and position * interval <= now:
                data = (
                    {"type": "presence", "client_id": str(position % writers), "cursor": {"x": position, "y": 0}}
                    if kind == "presence"
                    else {"type": "op", **op_event(position)}
                )
                entries.append((f"{position}-0".encode(), {b"data": json.dumps(data).encode()}))
                position += 1
            return [(key.encode(), entries)]

        async def advance(seconds: float) -> None:
            nonlocal now
            now += seconds

        async def read() -> list[bytes]:
            frames = stream_sketchpad_sse(1, "sketchpad", can_read=can_read)
            try:
                return [await anext(frames) for _ in range(event_count)]
            finally:
                await frames.aclose()

        client.xread.side_effect = read_batch
        with (
            patch("products.canvas.backend.sketchpad_stream.redis_module.get_async_client", return_value=client),
            patch("products.canvas.backend.sketchpad_stream.asyncio.sleep", side_effect=advance),
        ):
            frames = asyncio.run(read())

        payloads = [json.loads(frame.split(b"data: ", 1)[1]) for frame in frames]
        assert [data["cursor"]["x"] if kind == "presence" else data["seq"] for data in payloads] == list(
            range(event_count)
        )
        assert can_read.await_count <= max_checks
        assert now <= max_time

    @parameterized.expand([("before_connect", [False], 0), ("after_event", [True, True, False], 1)])
    def test_access_loss_stops_events(self, _name: str, access: list[bool], expected_frames: int) -> None:
        client = AsyncMock()
        client.xrevrange.return_value = []
        client.xread.return_value = [
            (b"ops", [(b"1-0", {b"data": json.dumps({"type": "op", **op_event(1)}).encode()})])
        ]

        async def read() -> list[bytes]:
            return [
                frame async for frame in stream_sketchpad_sse(1, "sketchpad", can_read=AsyncMock(side_effect=access))
            ]

        with (
            patch("products.canvas.backend.sketchpad_stream.redis_module.get_async_client", return_value=client),
            patch("products.canvas.backend.sketchpad_stream.asyncio.sleep", new_callable=AsyncMock),
        ):
            frames = asyncio.run(read())

        assert len(frames) == expected_frames
        if frames:
            assert b"event: op" in frames[0]


class TestSketchpadStream(BaseTest):
    def test_publish_presence_appends_entry_with_ttl(self):
        publish_presence(
            self.team.pk,
            "board1",
            client_id="client1",
            user_id=7,
            user_name="Grace Hopper",
            user_uuid="0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b",
            user_email="grace@example.com",
            cursor={"x": 120.5, "y": -40.0},
            viewport={"x": 0.0, "y": 0.0, "zoom": 1.0},
            selected_ids=["kpi"],
            carets=[{"key": "note", "anchor": "a-1", "focus": "a-1"}],
        )

        client = redis.get_client()
        stream_key = PRESENCE_STREAM_KEY_PATTERN.format(team_id=self.team.pk, sketchpad_id="board1")
        entries = client.xrange(stream_key)
        assert len(entries) == 1
        assert json.loads(entries[0][1][b"data"]) == {
            "type": "presence",
            "client_id": "client1",
            "user_id": 7,
            "user_name": "Grace Hopper",
            "user_uuid": "0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b",
            "user_email": "grace@example.com",
            "carets": [{"key": "note", "anchor": "a-1", "focus": "a-1"}],
            "cursor": {"x": 120.5, "y": -40.0},
            "viewport": {"x": 0.0, "y": 0.0, "zoom": 1.0},
            "selected_ids": ["kpi"],
        }
        assert 0 < client.ttl(stream_key) <= PRESENCE_TTL_SECONDS

    def test_resume_past_the_end_of_the_stream_asks_for_a_reload(self):
        publish_ops(self.team.pk, "board3", [op_event(40)])

        assert first_frame(self.team.pk, "board3", "12-0") == (b'event: reload\ndata: {"type":"reload","since":12}\n\n')

    def test_large_operations_use_a_reload_marker(self) -> None:
        event = op_event(1)
        event["op"] = {"type": "update_fragment", "id": "note", "patch": {"code": "x" * 100_000}}
        publish_ops(self.team.pk, "large-sketchpad", [event])

        entries = redis.get_client().xrange(
            OPS_STREAM_KEY_PATTERN.format(team_id=self.team.pk, sketchpad_id="large-sketchpad")
        )
        assert json.loads(entries[0][1][b"data"]) == {"type": "reload", "since": 0}
        assert (
            first_frame(self.team.pk, "large-sketchpad", "0-0")
            == b'event: reload\ndata: {"type":"reload","since":0}\n\n'
        )

    def test_resume_the_stream_still_holds_sends_no_reload(self):
        publish_ops(self.team.pk, "board4", [op_event(12), op_event(13)])
        entries = redis.get_client().xrange(OPS_STREAM_KEY_PATTERN.format(team_id=self.team.pk, sketchpad_id="board4"))
        assert [entry[0] for entry in entries] == [b"12-0", b"13-0"]

        assert first_frame(self.team.pk, "board4", "12-0") == (
            b"id: 13-0\nevent: op\ndata: "
            + json.dumps({"type": "op", **op_event(13)}, separators=(",", ":")).encode()
            + b"\n\n"
        )
