from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized

from products.canvas.backend.models import Sketchpad, SketchpadOp, SketchpadRecord
from products.canvas.backend.presentation.sketchpad.serializers import SketchpadAppendOpsSerializer
from products.tasks.backend.models import Channel, Task

FRAGMENT = {"id": "note", "x": 0, "y": 0, "w": 360, "h": 240, "code": "export default () => null"}
SNAPSHOT = {"schemaVersion": 1, "fragments": [FRAGMENT], "state": {"title": "Notes"}}


def append_payload(op: object, **overrides: object) -> dict[str, object]:
    return {"ops": [{"op_id": "test-op", "op": op}], "actor": {"kind": "user"}, **overrides}


class TestSketchpadValidation(SimpleTestCase):
    @parameterized.expand([("empty", 0, True), ("at_limit", 1000, True), ("over_limit", 1001, False)])
    def test_operation_batch_limit(self, _name: str, count: int, accepted: bool) -> None:
        serializer = SketchpadAppendOpsSerializer(
            data={
                "actor": {"kind": "user"},
                "ops": [
                    {"op_id": str(index), "op": {"type": "remove_fragment", "id": "note"}} for index in range(count)
                ],
            }
        )
        assert serializer.is_valid() is accepted
        if not accepted:
            assert serializer.errors["ops"]["non_field_errors"][0].code == "max_length"

    @parameterized.expand(
        [
            ("missing_fragment", {"type": "add_fragment"}),
            ("invalid_geometry", {"type": "add_fragment", "fragment": {**FRAGMENT, "w": "360"}}),
            ("unsafe_layer", {"type": "add_fragment", "fragment": {**FRAGMENT, "z": 2**53}}),
            ("invalid_patch", {"type": "update_fragment", "id": "note", "patch": {"code": None}}),
            ("missing_id", {"type": "remove_fragment"}),
            ("invalid_id", {"type": "bring_to_front", "id": 3}),
            ("reserved_state_key", {"type": "set_state", "key": "__proto__", "value": {}}),
            ("invalid_restore", {"type": "restore", "toSeq": 0, "snapshot": {"schemaVersion": 2}}),
            ("invalid_field", {"type": "edit_field", "key": "note", "kind": "text", "insert": [{}]}),
            ("large_field_edit", {"type": "edit_field", "key": "note", "kind": "text", "remove": ["a"] * 2001}),
            (
                "null_field_entry",
                {
                    "type": "set_state",
                    "key": "note",
                    "value": {"__field": "text", "entries": {"bad": None}, "removed": []},
                },
            ),
            (
                "invalid_field_key",
                {
                    "type": "set_state",
                    "key": "note",
                    "value": {"__field": "list", "entries": {"bad": {"k": 1, "v": "item"}}, "removed": []},
                },
            ),
            (
                "invalid_removed_id",
                {
                    "type": "restore",
                    "toSeq": 0,
                    "snapshot": {
                        "schemaVersion": 1,
                        "state": {"note": {"__field": "text", "entries": {}, "removed": [{}]}},
                    },
                },
            ),
        ]
    )
    def test_invalid_operation_is_rejected(self, _name: str, op: dict[str, Any]) -> None:
        serializer = SketchpadAppendOpsSerializer(data=append_payload(op))
        assert not serializer.is_valid()
        assert "op" in serializer.errors["ops"][0]

    @parameterized.expand(
        [
            ("missing_version", {}),
            ("invalid_fragment", {"schemaVersion": 1, "fragments": [{"id": "note"}]}),
            ("invalid_state", {"schemaVersion": 1, "state": []}),
            (
                "invalid_field_entries",
                {"schemaVersion": 1, "state": {"note": {"__field": "text", "entries": [], "removed": []}}},
            ),
        ]
    )
    def test_invalid_restore_is_rejected(self, _name: str, snapshot: dict[str, Any]) -> None:
        serializer = SketchpadAppendOpsSerializer(
            data=append_payload({"type": "restore", "toSeq": 0, "expectedSeq": 0, "snapshot": snapshot})
        )
        assert not serializer.is_valid()
        assert "op" in serializer.errors["ops"][0]

    def test_all_operation_types_preserve_their_data(self) -> None:
        ops = [
            {"type": "add_fragment", "fragment": FRAGMENT},
            {"type": "update_fragment", "id": "note", "patch": {"hidden": False, "title": ""}},
            {"type": "remove_fragment", "id": "note"},
            {"type": "bring_to_front", "id": "note"},
            {"type": "set_state", "key": "note", "value": None},
            {"type": "restore", "toSeq": 0, "snapshot": SNAPSHOT},
            {"type": "edit_field", "key": "note", "kind": "list", "insert": [{"id": "1", "k": "a", "v": None}]},
            {
                "type": "set_state",
                "key": "note",
                "value": {"__field": "list", "entries": {"one": {"k": "a0", "v": None}}, "removed": ["old"]},
            },
        ]
        payload = append_payload({}, ops=[{"op_id": str(index), "op": op} for index, op in enumerate(ops)])
        serializer = SketchpadAppendOpsSerializer(data=payload)
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data == payload

    def test_restore_can_exceed_the_single_edit_limit(self) -> None:
        snapshot = {
            "schemaVersion": 1,
            "fragments": [{**FRAGMENT, "id": f"note-{index}", "code": "x" * 150_000} for index in range(3)],
        }
        serializer = SketchpadAppendOpsSerializer(
            data=append_payload({"type": "restore", "toSeq": 1, "snapshot": snapshot})
        )
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["ops"][0]["op"]["snapshot"] == snapshot


class TestSketchpadValidationEndpoint(APIBaseTest):
    def test_read_shares_source_and_keeps_previews(self) -> None:
        channel = Channel.objects.for_team(self.team.id).create(team_id=self.team.id, name="general")
        sketchpad = Sketchpad.objects.for_team(self.team.id).create(
            team_id=self.team.id, channel=channel, name="Test sketchpad"
        )
        url = f"/api/projects/{self.team.id}/sketchpads/{sketchpad.id}/"
        operations = [
            {"op_id": key, "op": {"type": "add_fragment", "fragment": {**FRAGMENT, "id": key}}}
            for key in ["one", "two"]
        ]
        operations.append({"op_id": "move", "op": {"type": "update_fragment", "id": "one", "patch": {"x": 80}}})
        response = self.client.post(f"{url}ops/", {"ops": operations, "actor": {"kind": "user"}})
        assert response.status_code == 200
        assert response.json()["replayed"] == []
        task = Task.objects.create(team=self.team, channel=channel, created_by=self.user, title="Edit sketchpad")
        retry = self.client.post(
            f"{url}ops/",
            {
                "ops": [
                    {
                        "op_id": "one",
                        "op": {"type": "add_fragment", "fragment": {**FRAGMENT, "id": "one", "code": "different"}},
                    }
                ],
                "actor": {"kind": "agent", "task_id": str(task.id)},
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

        compact = self.client.get(url)
        assert compact.status_code == 200
        data = compact.json()
        assert len(data["source_versions"]) == 1
        assert self.client.post(f"{url}compiled/", {"refs": ["invalid"]}, format="json").status_code == 400
        with patch("products.canvas.backend.sketchpad.compiler.compile_sketchpad_fragments.apply_async"):
            compiled = self.client.post(f"{url}compiled/", {"refs": list(data["source_versions"])}, format="json")
        assert compiled.status_code == 200
        assert compiled.json() == {"results": {}}
        assert data["head_seq"] == 3
        for fragment in data["snapshot"]["fragments"]:
            assert "code" not in fragment
            assert data["source_versions"][fragment["codeRef"]] == FRAGMENT["code"]
        listed = self.client.get(f"/api/projects/{self.team.id}/sketchpads/?channel={channel.id}").json()["results"]
        assert listed[0]["fragment_count"] == 2
        assert listed[0]["preview"][0]["x"] == 80

        target = Channel.objects.for_team(self.team.id).create(team_id=self.team.id, name="Target")
        with CaptureQueriesContext(connection) as queries:
            response = self.client.patch(url, {"name": "Renamed", "pinned": True, "channel_id": str(target.id)})
        assert response.status_code == 204
        assert response.content == b""
        assert not any("posthog_sketchpadrecord" in query["sql"] for query in queries)
        sketchpad.refresh_from_db()
        assert (sketchpad.name, sketchpad.channel_id, sketchpad.pinned_at is not None) == ("Renamed", target.id, True)
        assert self.client.get(url).json()["snapshot"] == data["snapshot"]

    def test_list_reads_only_preview_fields(self) -> None:
        channel = Channel.objects.for_team(self.team.id).create(team_id=self.team.id, name="general")
        fragments = [{**FRAGMENT, "id": f"note-{index}", "x": index, "code": "x" * 2000} for index in range(30)]
        expected: dict[str, dict[str, object]] = {}
        for items in [fragments, []]:
            sketchpad = Sketchpad.objects.for_team(self.team.id).create(
                team_id=self.team.id, channel=channel, name="Test sketchpad", created_by=self.user
            )
            SketchpadRecord.objects.for_team(self.team.id).bulk_create(
                [
                    SketchpadRecord(
                        team_id=self.team.id,
                        sketchpad=sketchpad,
                        kind="fragment",
                        key=str(fragment["id"]),
                        value=fragment,
                        position=index,
                    )
                    for index, fragment in enumerate(items)
                ]
            )
            expected[str(sketchpad.pk)] = {
                "fragment_count": len(items),
                "preview": [{"x": index, "y": 0, "w": 360, "h": 240} for index in range(min(len(items), 24))],
            }

        with patch.object(Sketchpad, "from_db", wraps=Sketchpad.from_db) as loaded:
            response = self.client.get(f"/api/projects/{self.team.id}/sketchpads/")

        assert response.status_code == 200
        assert {
            row["id"]: {"fragment_count": row["fragment_count"], "preview": row["preview"]}
            for row in response.json()["results"]
        } == expected
        assert loaded.called
        assert all("record_fragments" not in call.args[1] for call in loaded.call_args_list)

    def test_invalid_operation_does_not_change_the_board(self) -> None:
        channel = Channel.objects.for_team(self.team.id).create(
            team_id=self.team.id, name="general", created_by=self.user
        )
        sketchpad = Sketchpad.objects.for_team(self.team.id).create(
            team_id=self.team.id, channel=channel, name="Test sketchpad"
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/sketchpads/{sketchpad.id}/ops/",
            append_payload({"type": "add_fragment"}),
            format="json",
        )
        assert response.status_code == 400
        sketchpad.refresh_from_db()
        assert sketchpad.head_seq == 0
        assert not SketchpadRecord.objects.for_team(self.team.id).filter(sketchpad=sketchpad).exists()
        assert not SketchpadOp.objects.for_team(self.team.id).filter(sketchpad=sketchpad).exists()
