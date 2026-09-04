from posthog.test.base import BaseTest

from django.db import connection
from django.test.utils import CaptureQueriesContext

from products.canvas.backend.board_log import append_ops
from products.canvas.backend.models import CanvasBoard, CanvasBoardOp, CanvasBoardRecord
from products.canvas.backend.presentation.serializers import CanvasBoardLogEntrySerializer, CanvasBoardSerializer
from products.tasks.backend.models import Channel


class TestCanvasBoardLog(BaseTest):
    def test_restore_keeps_source_history_and_applies_later_edits_in_order(self) -> None:
        channel = Channel.objects.for_team(self.team.id).create(team_id=self.team.id, name="general")
        fragment = {"id": "one", "x": 0, "y": 0, "w": 360, "h": 240, "z": -2, "code": "export default () => null"}
        board = CanvasBoard.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            channel=channel,
            name="Test board",
            snapshot={"schemaVersion": 1, "fragments": [fragment], "state": {"old": True}},
            snapshot_seq=1,
            head_seq=1,
        )
        restored = {
            "schemaVersion": 1,
            "fragments": [{**fragment, "code": "export default () => 1"}],
            "state": {"text": None},
        }
        ops = [
            {"type": "restore", "snapshot": restored, "toSeq": 0},
            {"type": "edit_field", "key": "text", "kind": "text", "insert": [{"id": "a", "k": "a", "v": "A"}]},
            {"type": "bring_to_front", "id": "one"},
            {"type": "add_fragment", "fragment": fragment},
            {"type": "bring_to_front", "id": "one"},
        ]
        append_ops(
            board, [{"op_id": str(index), "op": op} for index, op in enumerate(ops)], "user", None, self.user, 0, None
        )
        board.refresh_from_db()
        snapshot = CanvasBoardSerializer(board).data["snapshot"]
        assert snapshot["fragments"][0]["z"] == 1
        assert snapshot["fragments"][0]["code"] == fragment["code"]
        assert snapshot["state"] == {"text": {"__field": "text", "entries": {"a": {"k": "a", "v": "A"}}, "removed": []}}
        assert CanvasBoardRecord.objects.for_team(self.team.id).filter(board=board, kind="source").count() == 2
        history = CanvasBoardLogEntrySerializer(
            CanvasBoardOp.objects.for_team(self.team.id)
            .filter(board=board)
            .select_related("actor_user")
            .order_by("seq"),
            many=True,
        ).data
        assert history[0]["op"]["snapshot"] == restored

    def test_batch_preserves_order_and_retries_without_new_writes(self) -> None:
        channel = Channel.objects.for_team(self.team.id).create(team_id=self.team.id, name="general")
        board = CanvasBoard.objects.for_team(self.team.id).create(
            team_id=self.team.id, channel=channel, name="Test board", snapshot={"schemaVersion": 1}, records_seq=0
        )
        first = {"op_id": "first", "op": {"type": "set_state", "key": "one", "value": 1}}
        second = {"op_id": "second", "op": {"type": "set_state", "key": "two", "value": 2}}
        snapshot = {"schemaVersion": 1, "fragments": [], "state": {"one": 1, "two": 2}}

        with CaptureQueriesContext(connection) as queries:
            rows = append_ops(board, [first, first, second], "user", None, self.user, 0, snapshot)

        assert [row.seq for row in rows] == [1, 1, 2]
        assert sum('INSERT INTO "posthog_canvas_board_op"' in query["sql"] for query in queries) == 1
        assert not any("SELECT" in query["sql"] and '"snapshot"' in query["sql"] for query in queries)
        board.refresh_from_db()
        assert CanvasBoardSerializer(board).data["snapshot"] == snapshot
        assert board.records_seq == board.head_seq == 2
        assert board.snapshot == {"schemaVersion": 1}
        assert CanvasBoardOp.objects.for_team(self.team.id).filter(board=board).count() == 2

        with CaptureQueriesContext(connection) as queries:
            retried = append_ops(board, [first, second], "user", None, self.user, 2, snapshot)

        assert [row.pk for row in retried] == [rows[0].pk, rows[2].pk]
        assert not any(query["sql"].startswith(("INSERT", "UPDATE")) for query in queries)

        restored = {"schemaVersion": 1, "fragments": [], "state": {}}
        append_ops(
            board,
            [{"op_id": "restore", "op": {"type": "restore", "toSeq": 0, "snapshot": restored}}],
            "user",
            None,
            self.user,
            2,
            None,
        )
        board.refresh_from_db()
        assert CanvasBoardSerializer(board).data["snapshot"] == restored
        assert board.records_seq == board.head_seq == 3

    def test_moves_do_not_read_or_write_source_or_state_and_history_still_loads(self) -> None:
        channel = Channel.objects.for_team(self.team.id).create(team_id=self.team.id, name="general")
        board = CanvasBoard.objects.for_team(self.team.id).create(
            team_id=self.team.id, channel=channel, name="Test board", records_seq=0
        )
        code = "export default () => null;" + " ".ljust(100_000)
        fragments = [{"id": key, "x": 0, "y": 0, "w": 360, "h": 240, "code": code} for key in ["one", "two"]]
        append_ops(
            board,
            [{"op_id": f["id"], "op": {"type": "add_fragment", "fragment": f}} for f in fragments],
            "user",
            None,
            self.user,
            0,
            None,
        )
        append_ops(
            board,
            [{"op_id": "state", "op": {"type": "set_state", "key": "large", "value": "large-state-" * 1000}}],
            "user",
            None,
            self.user,
            0,
            None,
        )
        records = CanvasBoardRecord.objects.for_team(self.team.id).filter(board=board)
        assert records.filter(kind="source").count() == 1
        stored_ops = CanvasBoardOp.objects.for_team(self.team.id).filter(board=board).order_by("seq")
        assert "code" not in stored_ops.get(seq=1).op["fragment"]

        with CaptureQueriesContext(connection) as queries:
            append_ops(
                board,
                [{"op_id": "move", "op": {"type": "update_fragment", "id": "one", "patch": {"x": 80}}}],
                "user",
                None,
                self.user,
                0,
                None,
            )

        sql = "\n".join(query["sql"] for query in queries)
        assert "export default" not in sql
        assert "large-state-" not in sql
        assert '"snapshot"' not in sql
        assert records.get(kind="state", key="large").seq == 3
        assert records.get(kind="fragment", key="two").seq == 2
        assert records.get(kind="fragment", key="one").seq == 4
        board.refresh_from_db()
        snapshot = CanvasBoardSerializer(board).data["snapshot"]
        assert [fragment["id"] for fragment in snapshot["fragments"]] == ["one", "two"]
        assert snapshot["fragments"][0]["x"] == 80
        assert snapshot["fragments"][0]["code"] == code
        assert snapshot["state"]["large"] == "large-state-" * 1000
        history = CanvasBoardLogEntrySerializer(stored_ops.select_related("actor_user"), many=True).data
        assert history[0]["op"]["fragment"]["code"] == code
        assert "codeRef" not in history[0]["op"]["fragment"]

    def test_legacy_snapshot_and_log_migrate_without_trusting_a_stale_client(self) -> None:
        channel = Channel.objects.for_team(self.team.id).create(team_id=self.team.id, name="general")
        fragment = {"id": "one", "x": 0, "y": 0, "w": 360, "h": 240, "code": "export default () => null"}
        legacy = {"schemaVersion": 1, "fragments": [fragment], "state": {"plain": True}}
        board = CanvasBoard.objects.for_team(self.team.id).create(
            team_id=self.team.id, channel=channel, name="Test board", snapshot=legacy, snapshot_seq=1, head_seq=2
        )
        CanvasBoardOp.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            board=board,
            seq=2,
            op_id="old-edit",
            actor_kind="user",
            actor_user=self.user,
            op={"type": "edit_field", "key": "text", "kind": "text", "insert": [{"id": "a", "k": "a", "v": "A"}]},
        )
        operations = [
            {
                "type": "edit_field",
                "key": "text",
                "kind": "text",
                "remove": ["a"],
                "insert": [{"id": "b", "k": "b", "v": "B"}],
            },
            {"type": "edit_field", "key": "text", "kind": "text", "insert": [{"id": "a", "k": "a", "v": "A"}]},
            {"type": "edit_field", "key": "plain", "kind": "text", "insert": [{"id": "a", "k": "a", "v": "A"}]},
            {"type": "update_fragment", "id": "one", "patch": {"code": "export default () => 1"}},
            {"type": "bring_to_front", "id": "one"},
        ]
        append_ops(
            board,
            [{"op_id": str(index), "op": op} for index, op in enumerate(operations)],
            "user",
            None,
            self.user,
            1,
            legacy,
        )
        board.refresh_from_db()
        result = CanvasBoardSerializer(board).data
        assert result["snapshot_seq"] == result["head_seq"] == 7
        assert result["server_snapshots"] is True
        assert result["snapshot"]["state"] == {
            "plain": True,
            "text": {"__field": "text", "entries": {"b": {"k": "b", "v": "B"}}, "removed": ["a"]},
        }
        assert result["snapshot"]["fragments"][0] == {
            **fragment,
            "code": "export default () => 1",
            "codeVersion": 2,
            "z": 1,
        }
        assert board.snapshot == legacy
