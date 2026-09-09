from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from products.canvas.backend.models import Sketchpad, SketchpadOp, SketchpadRecord
from products.canvas.backend.presentation.sketchpad.serializers import (
    SketchpadHydratedLogEntrySerializer,
    SketchpadOpsPageSerializer,
    SketchpadSerializer,
)
from products.canvas.backend.sketchpad.compiler import compile_sketchpad_fragments, compiled_fragments
from products.canvas.backend.sketchpad.log import SketchpadHistoryCompacted, append_ops
from products.canvas.backend.sketchpad.records import with_sketchpad_records
from products.tasks.backend.models import Channel


class TestSketchpadLog(BaseTest):
    @patch("products.canvas.backend.sketchpad.log.SKETCHPAD_COMPACTION_CHUNK", 2)
    @patch("products.canvas.backend.sketchpad.log.SKETCHPAD_HISTORY_LIMIT", 3)
    def test_compacts_old_ops_into_a_checkpoint_and_rejects_stale_retries(self) -> None:
        channel = Channel.objects.for_team(self.team.id).create(team_id=self.team.id, name="general")
        sketchpad = Sketchpad.objects.for_team(self.team.id).create(
            team_id=self.team.id, channel=channel, name="History test"
        )
        first = {
            "id": "note",
            "x": 0,
            "y": 0,
            "w": 360,
            "h": 240,
            "code": "export default () => 1",
        }
        second = "export default () => 2"
        ops = [
            {"op_id": "add", "op": {"type": "add_fragment", "fragment": first}},
            {"op_id": "edit", "op": {"type": "update_fragment", "id": "note", "patch": {"code": second}}},
            {"op_id": "state", "op": {"type": "set_state", "key": "one", "value": 1}},
            {"op_id": "state-2", "op": {"type": "set_state", "key": "two", "value": 2}},
        ]
        append_ops(sketchpad, ops, "user", None, self.user)
        sketchpad.refresh_from_db()

        assert sketchpad.history_start_seq == 2
        assert sketchpad.history_snapshot["fragments"][0]["code"] == second
        retained = SketchpadOp.objects.for_team(self.team.id).filter(sketchpad=sketchpad).order_by("seq")
        assert list(retained.values_list("seq", flat=True)) == [3, 4]
        sources = SketchpadRecord.objects.for_team(self.team.id).filter(sketchpad=sketchpad, kind="source")
        assert list(sources.values_list("value", flat=True)) == [second]

        with self.assertRaises(SketchpadHistoryCompacted):
            append_ops(
                sketchpad,
                [{"op_id": "add", "op": {"type": "set_state", "key": "bad", "value": True}}],
                "user",
                None,
                self.user,
                base_seq=0,
            )
        replay = append_ops(sketchpad, [ops[2]], "user", None, self.user, base_seq=0)
        assert replay.results[0].seq == 3

    def test_compiled_sources_are_shared_and_removed_after_the_last_fragment(self) -> None:
        channel = Channel.objects.for_team(self.team.id).create(team_id=self.team.id, name="general")
        sketchpad = Sketchpad.objects.for_team(self.team.id).create(
            team_id=self.team.id, channel=channel, name="Compile test"
        )
        fragment = {"id": "one", "x": 0, "y": 0, "w": 360, "h": 240, "code": "export default () => <div>Ready</div>"}
        append_ops(
            sketchpad,
            [
                {"op_id": "one", "op": {"type": "add_fragment", "fragment": fragment}},
                {"op_id": "two", "op": {"type": "add_fragment", "fragment": {**fragment, "id": "two"}}},
            ],
            "user",
            None,
            self.user,
        )
        records = SketchpadRecord.objects.for_team(self.team.id).filter(sketchpad=sketchpad)
        ref = records.get(kind="source").key
        with patch("products.canvas.backend.sketchpad.compiler.compile_sketchpad_fragments.apply_async") as enqueue:
            with self.captureOnCommitCallbacks(execute=True):
                for _ in range(5):
                    assert compiled_fragments(sketchpad, [ref]) == {}
            assert enqueue.call_count == 1
            compile_sketchpad_fragments(*enqueue.call_args.kwargs["args"])
            result = compiled_fragments(sketchpad, [ref])[ref]
            assert result.error is None
            assert result.imports == ["react/jsx-runtime"]
            with patch("products.canvas.backend.sketchpad.compiler.subprocess.run") as run:
                compile_sketchpad_fragments(*enqueue.call_args.kwargs["args"])
                assert not run.called
            assert records.filter(kind="compiled").count() == 1
        for index, fragment_id in enumerate(["one", "two"]):
            append_ops(
                sketchpad,
                [{"op_id": f"remove-{fragment_id}", "op": {"type": "remove_fragment", "id": fragment_id}}],
                "user",
                None,
                self.user,
            )
            assert records.filter(kind="compiled").count() == 1 - index

    def test_restore_keeps_source_history_and_applies_later_edits_in_order(self) -> None:
        channel = Channel.objects.for_team(self.team.id).create(team_id=self.team.id, name="general")
        fragment = {"id": "one", "x": 0, "y": 0, "w": 360, "h": 240, "z": -2, "code": "export default () => null"}
        sketchpad = Sketchpad.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            channel=channel,
            name="Test sketchpad",
        )
        restored = {
            "schemaVersion": 1,
            "fragments": [{**fragment, "code": "export default () => 1"}],
            "state": {"text": None},
        }
        ops = [
            {"type": "restore", "snapshot": restored, "toSeq": 0, "expectedSeq": 0},
            {"type": "edit_field", "key": "text", "kind": "text", "insert": [{"id": "a", "k": "a", "v": "A"}]},
            {"type": "bring_to_front", "id": "one"},
            {"type": "add_fragment", "fragment": fragment},
            {"type": "bring_to_front", "id": "one"},
        ]
        append_ops(
            sketchpad, [{"op_id": str(index), "op": op} for index, op in enumerate(ops)], "user", None, self.user
        )
        sketchpad.refresh_from_db()
        data = SketchpadSerializer(
            with_sketchpad_records(Sketchpad.objects.for_team(self.team.id), self.team.id).get(pk=sketchpad.pk)
        ).data
        snapshot = data["snapshot"]
        assert snapshot["fragments"][0]["z"] == 1
        assert data["source_versions"][snapshot["fragments"][0]["codeRef"]] == fragment["code"]
        assert snapshot["state"] == {"text": {"__field": "text", "entries": {"a": {"k": "a", "v": "A"}}, "removed": []}}
        assert SketchpadRecord.objects.for_team(self.team.id).filter(sketchpad=sketchpad, kind="source").count() == 2
        history = SketchpadHydratedLogEntrySerializer(
            SketchpadOp.objects.for_team(self.team.id)
            .filter(sketchpad=sketchpad)
            .select_related("actor_user")
            .order_by("seq"),
            many=True,
        ).data
        assert history[0]["op"]["snapshot"] == restored
        with self.assertRaises(ValidationError):
            append_ops(
                sketchpad,
                [
                    {"op_id": "rolled-back", "op": {"type": "set_state", "key": "unsaved", "value": True}},
                    {"op_id": "stale", "op": ops[0]},
                ],
                "user",
                None,
                self.user,
            )
        sketchpad.refresh_from_db()
        assert sketchpad.head_seq == 5
        assert (
            SketchpadSerializer(
                with_sketchpad_records(Sketchpad.objects.for_team(self.team.id), self.team.id).get(pk=sketchpad.pk)
            ).data["snapshot"]
            == snapshot
        )

    def test_batch_preserves_order_and_retries_without_new_writes(self) -> None:
        channel = Channel.objects.for_team(self.team.id).create(team_id=self.team.id, name="general")
        sketchpad = Sketchpad.objects.for_team(self.team.id).create(
            team_id=self.team.id, channel=channel, name="Test sketchpad"
        )
        first = {"op_id": "first", "op": {"type": "set_state", "key": "one", "value": 1}}
        second = {"op_id": "second", "op": {"type": "set_state", "key": "two", "value": 2}}
        snapshot = {"schemaVersion": 1, "fragments": [], "state": {"one": 1, "two": 2}}

        with CaptureQueriesContext(connection) as queries:
            result = append_ops(sketchpad, [first, first, second], "user", None, self.user)

        rows = result.results
        assert [row.op_id for row in result.replayed] == ["first"]
        assert [row.seq for row in rows] == [1, 1, 2]
        assert sum('INSERT INTO "posthog_sketchpad_op"' in query["sql"] for query in queries) == 1
        assert not any("SELECT" in query["sql"] and '"snapshot"' in query["sql"] for query in queries)
        sketchpad.refresh_from_db()
        assert (
            SketchpadSerializer(
                with_sketchpad_records(Sketchpad.objects.for_team(self.team.id), self.team.id).get(pk=sketchpad.pk)
            ).data["snapshot"]
            == snapshot
        )
        assert sketchpad.head_seq == 2
        assert SketchpadOp.objects.for_team(self.team.id).filter(sketchpad=sketchpad).count() == 2

        with CaptureQueriesContext(connection) as queries:
            retried = append_ops(sketchpad, [first, second], "user", None, self.user)

        assert [row.pk for row in retried.results] == [rows[0].pk, rows[2].pk]
        assert retried.replayed == retried.results
        assert not any(query["sql"].startswith(("INSERT", "UPDATE")) for query in queries)

        restored = {"schemaVersion": 1, "fragments": [], "state": {}}
        append_ops(
            sketchpad,
            [{"op_id": "restore", "op": {"type": "restore", "toSeq": 0, "snapshot": restored, "expectedSeq": 2}}],
            "user",
            None,
            self.user,
        )
        sketchpad.refresh_from_db()
        assert (
            SketchpadSerializer(
                with_sketchpad_records(Sketchpad.objects.for_team(self.team.id), self.team.id).get(pk=sketchpad.pk)
            ).data["snapshot"]
            == restored
        )
        assert sketchpad.head_seq == 3

    def test_moves_do_not_read_or_write_source_or_state_and_history_still_loads(self) -> None:
        channel = Channel.objects.for_team(self.team.id).create(team_id=self.team.id, name="general")
        sketchpad = Sketchpad.objects.for_team(self.team.id).create(
            team_id=self.team.id, channel=channel, name="Test sketchpad"
        )
        code = "export default () => null;" + " ".ljust(100_000)
        fragments = [
            {"id": key, "x": 0, "y": 0, "w": 360, "h": 240, "z": 2**31, "code": code} for key in ["one", "two"]
        ]
        append_ops(
            sketchpad,
            [{"op_id": f["id"], "op": {"type": "add_fragment", "fragment": f}} for f in fragments],
            "user",
            None,
            self.user,
        )
        append_ops(
            sketchpad,
            [{"op_id": "state", "op": {"type": "set_state", "key": "large", "value": "large-state-" * 1000}}],
            "user",
            None,
            self.user,
        )
        records = SketchpadRecord.objects.for_team(self.team.id).filter(sketchpad=sketchpad)
        assert records.filter(kind="source").count() == 1
        stored_ops = SketchpadOp.objects.for_team(self.team.id).filter(sketchpad=sketchpad).order_by("seq")
        assert "code" not in stored_ops.get(seq=1).op["fragment"]
        before = {(row.kind, row.key): row.updated_at for row in records}

        with freeze_time(timezone.now() + timedelta(seconds=1)), CaptureQueriesContext(connection) as queries:
            append_ops(
                sketchpad,
                [{"op_id": "move", "op": {"type": "update_fragment", "id": "one", "patch": {"x": 80}}}],
                "user",
                None,
                self.user,
            )

        sql = "\n".join(query["sql"] for query in queries)
        assert "export default" not in sql
        assert "large-state-" not in sql
        assert '"snapshot"' not in sql
        assert records.get(kind="state", key="large").updated_at == before[("state", "large")]
        assert records.get(kind="fragment", key="two").updated_at == before[("fragment", "two")]
        assert records.get(kind="fragment", key="one").updated_at > before[("fragment", "one")]
        sketchpad.refresh_from_db()
        data = SketchpadSerializer(
            with_sketchpad_records(Sketchpad.objects.for_team(self.team.id), self.team.id).get(pk=sketchpad.pk)
        ).data
        snapshot = data["snapshot"]
        assert [fragment["id"] for fragment in snapshot["fragments"]] == ["one", "two"]
        assert snapshot["fragments"][0]["x"] == 80
        assert data["source_versions"][snapshot["fragments"][0]["codeRef"]] == code
        assert snapshot["state"]["large"] == "large-state-" * 1000
        page = SketchpadOpsPageSerializer(
            {
                "results": list(stored_ops.select_related("actor_user")),
                "head_seq": sketchpad.head_seq,
                "history_start_seq": sketchpad.history_start_seq,
                "history_snapshot": sketchpad.history_snapshot,
            }
        ).data
        assert len(page["source_versions"]) == 1
        for entry in page["results"][:2]:
            assert "code" not in entry["op"]["fragment"]
            assert page["source_versions"][entry["op"]["fragment"]["codeRef"]] == code
        history = SketchpadHydratedLogEntrySerializer(stored_ops.select_related("actor_user"), many=True).data
        assert history[0]["op"]["fragment"]["code"] == code
        assert "codeRef" not in history[0]["op"]["fragment"]
        append_ops(
            sketchpad, [{"op_id": "front", "op": {"type": "bring_to_front", "id": "one"}}], "user", None, self.user
        )
        assert records.get(kind="fragment", key="one").value["z"] == 2**31 + 1
        with self.assertRaises(ValidationError):
            append_ops(
                sketchpad,
                [
                    {"op_id": "limit", "op": {"type": "update_fragment", "id": "one", "patch": {"z": 2**53 - 1}}},
                    {"op_id": "overflow", "op": {"type": "bring_to_front", "id": "two"}},
                ],
                "user",
                None,
                self.user,
            )
        assert records.get(kind="fragment", key="one").value["z"] == 2**31 + 1

    @parameterized.expand([("text", "A"), ("list", ["A"])])
    def test_field_initialization_preserves_edits_and_rejects_stale_values(
        self, kind: str, value: str | list[str]
    ) -> None:
        channel = Channel.objects.for_team(self.team.id).create(team_id=self.team.id, name="general")
        sketchpad = Sketchpad.objects.for_team(self.team.id).create(
            team_id=self.team.id, channel=channel, name="Sketchpad"
        )
        initial = {"type": "set_state", "key": "text", "value": value}
        seed = {
            "type": "edit_field",
            "key": "text",
            "kind": kind,
            "initialValue": value,
            "insert": [{"id": "seed-0", "k": "a", "v": "A"}],
        }
        edit = {
            "type": "edit_field",
            "key": "text",
            "kind": kind,
            "remove": ["seed-0"] if kind == "text" else [],
            "insert": [{"id": "b" if kind == "text" else "seed-0", "k": "b", "v": "B"}],
        }
        for index, op in enumerate([initial, seed, edit, seed]):
            append_ops(sketchpad, [{"op_id": str(index), "op": op}], "user", None, self.user)
        data = SketchpadSerializer(
            with_sketchpad_records(Sketchpad.objects.for_team(self.team.id), self.team.id).get(pk=sketchpad.pk)
        ).data
        assert data["snapshot"]["state"]["text"] == {
            "__field": kind,
            "entries": {"b" if kind == "text" else "seed-0": {"k": "b", "v": "B"}},
            "removed": ["seed-0"] if kind == "text" else [],
        }
        append_ops(sketchpad, [{"op_id": "reset", "op": {**initial, "value": "C"}}], "user", None, self.user)
        with self.assertRaises(ValidationError):
            append_ops(sketchpad, [{"op_id": "stale-seed", "op": seed}], "user", None, self.user)
        assert (
            SketchpadSerializer(
                with_sketchpad_records(Sketchpad.objects.for_team(self.team.id), self.team.id).get(pk=sketchpad.pk)
            ).data["snapshot"]["state"]["text"]
            == "C"
        )
        append_ops(sketchpad, [{"op_id": "reset-again", "op": initial}], "user", None, self.user)
        append_ops(sketchpad, [{"op_id": "new-seed", "op": seed}], "user", None, self.user)
        assert (
            SketchpadSerializer(
                with_sketchpad_records(Sketchpad.objects.for_team(self.team.id), self.team.id).get(pk=sketchpad.pk)
            ).data["snapshot"]["state"]["text"]["entries"]["seed-0"]["v"]
            == "A"
        )
