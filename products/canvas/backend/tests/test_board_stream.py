import json
import asyncio

from posthog.test.base import BaseTest

from posthog import redis

from products.canvas.backend.board_presence import PRESENCE_STREAM_KEY_PATTERN, PRESENCE_TTL_SECONDS, publish_presence
from products.canvas.backend.board_stream import OPS_STREAM_KEY_PATTERN, publish_ops, stream_board_sse


def op_event(seq: int) -> dict:
    return {
        "seq": seq,
        "op_id": f"op-{seq}",
        "actor": {"kind": "user", "user_id": 7, "user_name": "Grace Hopper", "task_id": None},
        "created_at": "2026-09-03T10:00:00+00:00",
        "op": {"type": "bring_to_front", "id": "kpi"},
    }


def first_frame(team_id: int, board_id: str, last_event_id: str | None) -> bytes:
    async def read() -> bytes:
        frames = stream_board_sse(team_id, board_id, last_event_id=last_event_id)
        try:
            return await anext(frames)
        finally:
            await frames.aclose()

    return asyncio.run(read())


class TestCanvasBoardStream(BaseTest):
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
        stream_key = PRESENCE_STREAM_KEY_PATTERN.format(team_id=self.team.pk, board_id="board1")
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

    def test_publish_ops_puts_the_seq_in_the_stream_id(self):
        publish_ops(self.team.pk, "board2", [op_event(4), op_event(5)])

        client = redis.get_client()
        entries = client.xrange(OPS_STREAM_KEY_PATTERN.format(team_id=self.team.pk, board_id="board2"))
        assert [entry[0] for entry in entries] == [b"4-0", b"5-0"]
        payload = json.loads(entries[1][1][b"data"])
        assert payload["type"] == "op"
        assert payload["seq"] == 5

    def test_resume_past_the_end_of_the_stream_asks_for_a_reload(self):
        publish_ops(self.team.pk, "board3", [op_event(40)])

        assert first_frame(self.team.pk, "board3", "12-0") == (b'event: reload\ndata: {"type":"reload","since":12}\n\n')

    def test_resume_the_stream_still_holds_sends_no_reload(self):
        publish_ops(self.team.pk, "board4", [op_event(12), op_event(13)])

        assert first_frame(self.team.pk, "board4", "12-0") == (
            b"id: 13-0\nevent: op\ndata: "
            + json.dumps({"type": "op", **op_event(13)}, separators=(",", ":")).encode()
            + b"\n\n"
        )
