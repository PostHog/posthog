import json
from collections.abc import AsyncGenerator
from datetime import timedelta
from typing import Any, cast

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from django.db import connection
from django.http import StreamingHttpResponse
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog import redis
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.sync import database_sync_to_async

from products.canvas.backend.models import Sketchpad, SketchpadOp, SketchpadRecord
from products.canvas.backend.presentation.sketchpad.serializers import SketchpadAppendOpsSerializer
from products.canvas.backend.sketchpad.stream import OPS_STREAM_KEY_PATTERN
from products.tasks.backend.models import Channel, Task

FRAGMENT = {"id": "note", "x": 0, "y": 0, "w": 360, "h": 240, "code": "export default () => null"}
SNAPSHOT = {"schemaVersion": 1, "fragments": [FRAGMENT], "state": {"title": "Notes"}}


def append_payload(op: object, **overrides: object) -> dict[str, object]:
    return {
        "base_seq": 0,
        "ops": [{"op_id": "test-op", "op": op}],
        "actor": {"kind": "user"},
        **overrides,
    }


class TestSketchpadValidation(SimpleTestCase):
    @parameterized.expand([("empty", 0, True), ("at_limit", 1000, True), ("over_limit", 1001, False)])
    def test_operation_batch_limit(self, _name: str, count: int, accepted: bool) -> None:
        serializer = SketchpadAppendOpsSerializer(
            data={
                "base_seq": 0,
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
            ("large_restore_fragments", {"schemaVersion": 1, "fragments": [FRAGMENT] * 2001}),
            ("large_restore_state", {"schemaVersion": 1, "state": {f"k{index}": {} for index in range(2001)}}),
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
    @patch("products.canvas.backend.sketchpad.records.MAX_COLLECTION_ITEMS", 2)
    def test_cumulative_record_limits_allow_replacements_and_removals(self) -> None:
        channel = Channel.objects.for_team(self.team.id).create(team_id=self.team.id, name="general")
        sketchpad = Sketchpad.objects.for_team(self.team.id).create(
            team_id=self.team.id, channel=channel, name="Test sketchpad"
        )
        url = f"/api/projects/{self.team.id}/sketchpads/{sketchpad.id}/ops/"

        def append(op_id: str, op: dict[str, Any]) -> Any:
            sketchpad.refresh_from_db()
            return self.client.post(
                url,
                {"base_seq": sketchpad.head_seq, "ops": [{"op_id": op_id, "op": op}], "actor": {"kind": "user"}},
                format="json",
            )

        assert append("add-one", {"type": "add_fragment", "fragment": {**FRAGMENT, "id": "one"}}).status_code == 200
        assert append("add-two", {"type": "add_fragment", "fragment": {**FRAGMENT, "id": "two"}}).status_code == 200
        assert append("replace-two", {"type": "add_fragment", "fragment": {**FRAGMENT, "id": "two"}}).status_code == 200
        assert append("add-three", {"type": "add_fragment", "fragment": {**FRAGMENT, "id": "three"}}).status_code == 400
        assert append("remove-one", {"type": "remove_fragment", "id": "one"}).status_code == 200
        assert (
            append(
                "add-three-after-remove", {"type": "add_fragment", "fragment": {**FRAGMENT, "id": "three"}}
            ).status_code
            == 200
        )

        assert append("state-one", {"type": "set_state", "key": "one", "value": 1}).status_code == 200
        assert append("state-two", {"type": "set_state", "key": "two", "value": 2}).status_code == 200
        assert append("state-three", {"type": "set_state", "key": "three", "value": 3}).status_code == 400

    @patch("products.canvas.backend.sketchpad.records.MAX_COLLECTION_ITEMS", 2)
    def test_cumulative_shared_field_limits(self) -> None:
        channel = Channel.objects.for_team(self.team.id).create(team_id=self.team.id, name="general")
        sketchpad = Sketchpad.objects.for_team(self.team.id).create(
            team_id=self.team.id, channel=channel, name="Test sketchpad"
        )
        url = f"/api/projects/{self.team.id}/sketchpads/{sketchpad.id}/ops/"

        def edit(op_id: str, *, insert: list[dict[str, Any]] | None = None, remove: list[str] | None = None) -> Any:
            sketchpad.refresh_from_db()
            return self.client.post(
                url,
                {
                    "base_seq": sketchpad.head_seq,
                    "ops": [
                        {
                            "op_id": op_id,
                            "op": {
                                "type": "edit_field",
                                "key": "notes",
                                "kind": "list",
                                "insert": insert or [],
                                "remove": remove or [],
                            },
                        }
                    ],
                    "actor": {"kind": "user"},
                },
                format="json",
            )

        assert (
            edit("insert-two", insert=[{"id": "one", "k": "a", "v": 1}, {"id": "two", "k": "b", "v": 2}]).status_code
            == 200
        )
        assert edit("insert-third", insert=[{"id": "three", "k": "c", "v": 3}]).status_code == 400
        assert edit("remove-two", remove=["one", "two"]).status_code == 200
        assert edit("remove-third", remove=["three"]).status_code == 400

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
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"{url}ops/", {"base_seq": 0, "ops": operations, "actor": {"kind": "user"}}
            )
        assert response.status_code == 200
        assert response.json()["replayed"] == []
        task = Task.objects.create(team=self.team, channel=channel, created_by=self.user, title="Edit sketchpad")
        events = redis.get_client().xrange(
            OPS_STREAM_KEY_PATTERN.format(team_id=self.team.id, sketchpad_id=str(sketchpad.pk))
        )
        page = self.client.get(f"{url}ops/").json()
        streamed = [json.loads(fields[b"data"]) for _, fields in events]
        for event, entry in zip(streamed, page["results"], strict=True):
            assert {key: value for key, value in event.items() if key not in {"type", "op"}} == {
                key: value for key, value in entry.items() if key != "op"
            }
            if entry["op"]["type"] == "add_fragment":
                assert event["op"]["fragment"]["code"] == page["source_versions"][entry["op"]["fragment"]["codeRef"]]
            else:
                assert event["op"] == entry["op"]
        retry = self.client.post(
            f"{url}ops/",
            {
                "base_seq": 0,
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

    @parameterized.expand(
        [("deleted",), ("private",), ("membership",), ("disabled_user",), ("token_scope",), ("token_revoked",)]
    )
    def test_open_stream_stops_after_access_changes(self, change: str) -> None:
        channel = Channel.objects.for_team(self.team.id).create(team_id=self.team.id, name="general")
        private_channel = Channel.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            name="personal",
            channel_type=Channel.ChannelType.PERSONAL,
            created_by=self._create_user("sketchpad-owner@example.com"),
        )
        sketchpad = Sketchpad.objects.for_team(self.team.id).create(
            team_id=self.team.id, channel=channel, name="Test sketchpad"
        )
        token = None
        if change.startswith("token_"):
            app = OAuthApplication.objects.create(
                name="desktop",
                user=self.user,
                organization=self.organization,
                client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
                authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                algorithm="RS256",
                redirect_uris="https://example.com/callback",
            )
            token = OAuthAccessToken.objects.create(
                user=self.user,
                application=app,
                token="pha_sketchpad_stream_test",
                scope="canvas:read",
                expires=timezone.now() + timedelta(hours=1),
                scoped_teams=[],
                scoped_organizations=[],
            )
            self.client.logout()
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        client = AsyncMock()
        client.xrevrange.return_value = []
        client.time.return_value = (1_800_000_000, 0)
        client.xread.return_value = [(b"ops", [(b"1-0", {b"data": b'{"type":"op","seq":1}'})])]

        def revoke_access() -> None:
            if change == "membership":
                self.organization.memberships.filter(user=self.user).delete()
            elif change == "disabled_user":
                self.user.is_active = False
                self.user.save(update_fields=["is_active"])
            elif change == "token_scope":
                assert token is not None
                token.scope = "annotation:read"
                token.save(update_fields=["scope"])
            elif change == "token_revoked":
                assert token is not None
                token.delete()
            else:
                updates = {"deleted": True} if change == "deleted" else {"channel_id": private_channel.pk}
                Sketchpad.objects.for_team(self.team.id).filter(pk=sketchpad.pk).update(**updates)

        with (
            patch("posthog.api.streaming.settings.SERVER_GATEWAY_INTERFACE", "ASGI"),
            patch("products.canvas.backend.sketchpad.stream.ACCESS_RECHECK_SECONDS", 0),
            patch("products.canvas.backend.sketchpad.stream.redis_module.get_async_client", return_value=client),
        ):
            response = cast(
                StreamingHttpResponse,
                self.client.get(f"/api/projects/{self.team.id}/sketchpads/{sketchpad.id}/stream/"),
            )
            assert response.status_code == 200

            async def read() -> None:
                frames = response.streaming_content
                assert isinstance(frames, AsyncGenerator)
                try:
                    assert b"event: op" in await anext(frames)
                    await database_sync_to_async(revoke_access)()
                    with self.assertRaises(StopAsyncIteration):
                        await anext(frames)
                finally:
                    await frames.aclose()

            async_to_sync(read)()
