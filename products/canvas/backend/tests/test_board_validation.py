from collections.abc import AsyncGenerator
from typing import Any, cast

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from django.http import StreamingHttpResponse
from django.test import SimpleTestCase

from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.sync import database_sync_to_async

from products.canvas.backend.models import CanvasBoard, CanvasBoardOp
from products.canvas.backend.presentation.serializers import CanvasBoardAppendOpsSerializer
from products.tasks.backend.models import Channel

FRAGMENT = {"id": "note", "x": 0, "y": 0, "w": 360, "h": 240, "code": "export default () => null"}
SNAPSHOT = {"schemaVersion": 1, "fragments": [FRAGMENT], "state": {"title": "Notes"}}


def append_payload(op: object, **overrides: object) -> dict[str, object]:
    return {"ops": [{"op_id": "test-op", "op": op}], "actor": {"kind": "user"}, "base_seq": 0, **overrides}


class TestCanvasBoardValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("missing_fragment", {"type": "add_fragment"}),
            ("invalid_geometry", {"type": "add_fragment", "fragment": {**FRAGMENT, "w": "360"}}),
            ("invalid_patch", {"type": "update_fragment", "id": "note", "patch": {"code": None}}),
            ("missing_id", {"type": "remove_fragment"}),
            ("invalid_id", {"type": "bring_to_front", "id": 3}),
            ("reserved_state_key", {"type": "set_state", "key": "__proto__", "value": {}}),
            ("invalid_restore", {"type": "restore", "toSeq": 0, "snapshot": {"schemaVersion": 2}}),
            ("invalid_field", {"type": "edit_field", "key": "note", "kind": "text", "insert": [{}]}),
            ("large_field_edit", {"type": "edit_field", "key": "note", "kind": "text", "remove": ["a"] * 2001}),
        ]
    )
    def test_invalid_operation_is_rejected(self, _name: str, op: dict[str, Any]) -> None:
        serializer = CanvasBoardAppendOpsSerializer(data=append_payload(op))
        assert not serializer.is_valid()
        assert "op" in serializer.errors["ops"][0]

    @parameterized.expand(
        [
            ("missing_version", {}),
            ("invalid_fragment", {"schemaVersion": 1, "fragments": [{"id": "note"}]}),
            ("invalid_state", {"schemaVersion": 1, "state": []}),
        ]
    )
    def test_invalid_checkpoint_is_rejected(self, _name: str, snapshot: dict[str, Any]) -> None:
        serializer = CanvasBoardAppendOpsSerializer(data=append_payload({}, ops=[], snapshot=snapshot))
        assert not serializer.is_valid()
        assert "snapshot" in serializer.errors

    def test_all_operation_types_preserve_their_data(self) -> None:
        ops = [
            {"type": "add_fragment", "fragment": FRAGMENT},
            {"type": "update_fragment", "id": "note", "patch": {"hidden": False, "title": ""}},
            {"type": "remove_fragment", "id": "note"},
            {"type": "bring_to_front", "id": "note"},
            {"type": "set_state", "key": "note", "value": None},
            {"type": "restore", "toSeq": 0, "snapshot": SNAPSHOT},
            {"type": "edit_field", "key": "note", "kind": "list", "insert": [{"id": "1", "k": "a", "v": None}]},
        ]
        payload = append_payload(
            {}, ops=[{"op_id": str(index), "op": op} for index, op in enumerate(ops)], snapshot=SNAPSHOT
        )
        serializer = CanvasBoardAppendOpsSerializer(data=payload)
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data == payload

    def test_restore_can_exceed_the_single_edit_limit(self) -> None:
        snapshot = {
            "schemaVersion": 1,
            "fragments": [{**FRAGMENT, "id": f"note-{index}", "code": "x" * 150_000} for index in range(3)],
        }
        serializer = CanvasBoardAppendOpsSerializer(
            data=append_payload({"type": "restore", "toSeq": 1, "snapshot": snapshot})
        )
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["ops"][0]["op"]["snapshot"] == snapshot


class TestCanvasBoardValidationEndpoint(APIBaseTest):
    def test_compact_read_shares_source_and_keeps_legacy_reads_and_previews(self) -> None:
        channel = Channel.objects.for_team(self.team.id).create(team_id=self.team.id, name="general")
        board = CanvasBoard.objects.for_team(self.team.id).create(
            team_id=self.team.id, channel=channel, name="Test board", records_seq=0
        )
        url = f"/api/projects/{self.team.id}/canvas_boards/{board.id}/"
        operations = [
            {"op_id": key, "op": {"type": "add_fragment", "fragment": {**FRAGMENT, "id": key}}}
            for key in ["one", "two"]
        ]
        operations.append({"op_id": "move", "op": {"type": "update_fragment", "id": "one", "patch": {"x": 80}}})
        response = self.client.post(f"{url}ops/", {"ops": operations, "actor": {"kind": "user"}, "base_seq": 0})
        assert response.status_code == 200
        assert response.json()["replayed"] == []
        retry = self.client.post(
            f"{url}ops/",
            {
                "ops": [
                    {
                        "op_id": "one",
                        "op": {"type": "add_fragment", "fragment": {**FRAGMENT, "id": "one", "code": "different"}},
                    }
                ],
                "actor": {"kind": "agent", "task_id": "another-task"},
                "base_seq": 0,
            },
            format="json",
        )
        assert retry.status_code == 200
        replayed = retry.json()["replayed"]
        assert len(replayed) == 1
        assert replayed[0]["op"]["fragment"]["code"] == FRAGMENT["code"]
        assert replayed[0]["op"]["fragment"]["x"] == 0
        assert replayed[0]["actor"]["kind"] == "user"
        assert replayed[0]["seq"] == 1
        assert retry.json()["head_seq"] == 3

        compact = self.client.get(f"{url}?compact=true")
        assert compact.status_code == 200
        data = compact.json()
        assert len(data["source_versions"]) == 1
        assert data["snapshot_seq"] == data["head_seq"] == 3
        assert data["ops_after_snapshot"] == []
        for fragment in data["snapshot"]["fragments"]:
            assert "code" not in fragment
            assert data["source_versions"][fragment["codeRef"]] == FRAGMENT["code"]
        legacy = self.client.get(url).json()
        assert "source_versions" not in legacy
        assert [fragment["code"] for fragment in legacy["snapshot"]["fragments"]] == [FRAGMENT["code"]] * 2
        listed = self.client.get(f"/api/projects/{self.team.id}/canvas_boards/?channel={channel.id}").json()["results"]
        assert listed[0]["fragment_count"] == 2
        assert listed[0]["preview"][0]["x"] == 80

    def test_list_reads_only_preview_fields(self) -> None:
        channel = Channel.objects.for_team(self.team.id).create(team_id=self.team.id, name="general")
        fragments = [{**FRAGMENT, "id": f"note-{index}", "x": index, "code": "x" * 2000} for index in range(30)]
        cases: list[tuple[object, int, int]] = [
            ({"fragments": fragments, "state": {"text": "x" * 10_000}}, 30, 24),
            ({"fragments": [None, {"x": 1}, *fragments]}, 32, 22),
            ({"fragments": {}}, 0, 0),
            ([], 0, 0),
        ]
        expected: dict[str, dict[str, object]] = {}
        for snapshot, count, boxes in cases:
            board = CanvasBoard.objects.for_team(self.team.id).create(
                team_id=self.team.id, channel=channel, name="Test board", snapshot=snapshot, created_by=self.user
            )
            expected[str(board.pk)] = {
                "fragment_count": count,
                "preview": [{"x": index, "y": 0, "w": 360, "h": 240} for index in range(boxes)],
            }

        with patch.object(CanvasBoard, "from_db", wraps=CanvasBoard.from_db) as loaded:
            response = self.client.get(f"/api/projects/{self.team.id}/canvas_boards/")

        assert response.status_code == 200
        assert {
            row["id"]: {"fragment_count": row["fragment_count"], "preview": row["preview"]}
            for row in response.json()["results"]
        } == expected
        assert loaded.called
        assert all("snapshot" not in call.args[1] for call in loaded.call_args_list)

    def test_invalid_operation_does_not_change_the_board(self) -> None:
        channel = Channel.objects.for_team(self.team.id).create(
            team_id=self.team.id, name="general", created_by=self.user
        )
        board = CanvasBoard.objects.for_team(self.team.id).create(
            team_id=self.team.id, channel=channel, name="Test board", snapshot=SNAPSHOT
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/canvas_boards/{board.id}/ops/",
            append_payload({"type": "add_fragment"}),
            format="json",
        )
        assert response.status_code == 400
        board.refresh_from_db()
        assert board.head_seq == 0
        assert board.snapshot == SNAPSHOT
        assert not CanvasBoardOp.objects.for_team(self.team.id).filter(board=board).exists()

    @parameterized.expand([("deleted",), ("private",)])
    def test_open_stream_stops_after_access_changes(self, change: str) -> None:
        channel = Channel.objects.for_team(self.team.id).create(team_id=self.team.id, name="general")
        private_channel = Channel.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            name="personal",
            channel_type=Channel.ChannelType.PERSONAL,
            created_by=self._create_user("board-owner@example.com"),
        )
        board = CanvasBoard.objects.for_team(self.team.id).create(
            team_id=self.team.id, channel=channel, name="Test board", snapshot=SNAPSHOT
        )
        client = AsyncMock()
        client.xrevrange.return_value = []
        client.xread.return_value = [(b"ops", [(b"1-0", {b"data": b'{"type":"op","seq":1}'})])]
        update_board = database_sync_to_async(CanvasBoard.objects.for_team(self.team.id).filter(pk=board.pk).update)

        with (
            patch("products.canvas.backend.presentation.views.SERVER_GATEWAY_INTERFACE", "ASGI"),
            patch("products.canvas.backend.board_stream.redis_module.get_async_client", return_value=client),
        ):
            response = cast(
                StreamingHttpResponse, self.client.get(f"/api/projects/{self.team.id}/canvas_boards/{board.id}/stream/")
            )
            assert response.status_code == 200

            async def read() -> None:
                frames = response.streaming_content
                assert isinstance(frames, AsyncGenerator)
                try:
                    assert b"event: op" in await anext(frames)
                    updates = {"deleted": True} if change == "deleted" else {"channel_id": private_channel.pk}
                    await update_board(**updates)
                    with self.assertRaises(StopAsyncIteration):
                        await anext(frames)
                finally:
                    await frames.aclose()

            async_to_sync(read)()
