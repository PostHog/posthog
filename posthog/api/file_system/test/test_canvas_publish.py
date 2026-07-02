from typing import cast

from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models.file_system.file_system import FileSystem


class TestDesktopCanvasPublishAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        # Staff gate mirrors the desktop/web file system beta gating.
        self.user.is_staff = True
        self.user.save()

    def _create_dashboard(self, path: str = "MyChannel/MyCanvas", meta: dict | None = None) -> str:
        response = self.client.post(
            f"/api/projects/{self.team.id}/desktop_file_system/",
            {"path": path, "type": "dashboard", "meta": meta or {}},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        return cast(str, response.json()["id"])

    def _canvas_url(self, item_id: str) -> str:
        return f"/api/projects/{self.team.id}/desktop_file_system/{item_id}/canvas/"

    def test_publish_canvas_sets_code_and_appends_version(self):
        item_id = self._create_dashboard(meta={"channelId": "chan-1", "kind": "freeform"})

        response = self.client.patch(
            self._canvas_url(item_id),
            {"code": "export default () => <div>hi</div>", "prompt": "build a hello canvas"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        row = FileSystem.objects.get(id=item_id)
        meta = cast(dict, row.meta)
        self.assertEqual(meta["code"], "export default () => <div>hi</div>")
        self.assertEqual(meta["kind"], "freeform")
        # Pre-existing meta keys survive the merge.
        self.assertEqual(meta["channelId"], "chan-1")
        # One version appended, pointed at by currentVersionId, carrying the prompt.
        self.assertEqual(len(meta["versions"]), 1)
        version = meta["versions"][0]
        self.assertEqual(version["code"], "export default () => <div>hi</div>")
        self.assertEqual(version["prompt"], "build a hello canvas")
        self.assertEqual(meta["currentVersionId"], version["id"])

    def test_publish_canvas_appends_to_existing_history(self):
        item_id = self._create_dashboard()
        self.client.patch(self._canvas_url(item_id), {"code": "v1"})
        self.client.patch(self._canvas_url(item_id), {"code": "v2"})

        meta = cast(dict, FileSystem.objects.get(id=item_id).meta)
        self.assertEqual(meta["code"], "v2")
        self.assertEqual([v["code"] for v in meta["versions"]], ["v1", "v2"])
        self.assertEqual(meta["currentVersionId"], meta["versions"][-1]["id"])

    def test_publish_canvas_renames_via_name(self):
        item_id = self._create_dashboard(path="MyChannel/Old name")

        response = self.client.patch(
            self._canvas_url(item_id),
            {"code": "v1", "name": "New name"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        row = FileSystem.objects.get(id=item_id)
        # Leaf segment renamed, parent folder preserved.
        self.assertEqual(row.path, "MyChannel/New name")
        self.assertEqual(cast(dict, row.meta)["code"], "v1")

    def test_publish_canvas_without_name_keeps_path(self):
        item_id = self._create_dashboard(path="MyChannel/Keep me")

        self.client.patch(self._canvas_url(item_id), {"code": "v1"})

        self.assertEqual(FileSystem.objects.get(id=item_id).path, "MyChannel/Keep me")

    def test_publish_canvas_rejects_non_dashboard(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/desktop_file_system/",
            {"path": "AChannel", "type": "folder"},
        )
        folder_id = response.json()["id"]

        bad = self.client.patch(self._canvas_url(folder_id), {"code": "x"})
        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST, bad.json())

    def test_publish_canvas_requires_code(self):
        item_id = self._create_dashboard()

        # `code` is required by the serializer; omitting it is a 400, not a silent no-op.
        bad = self.client.patch(self._canvas_url(item_id), {"prompt": "only a prompt"})
        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST, bad.json())
        self.assertIn("code", bad.json())

    def test_delete_canvas_removes_ref_less_dashboard_row(self):
        # Desktop canvases are `dashboard`-typed rows with no ref; deleting one must not
        # trip the "without a reference" guard meant for real object-backed rows.
        item_id = self._create_dashboard()

        response = self.client.delete(f"/api/projects/{self.team.id}/desktop_file_system/{item_id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT, response.content)
        self.assertFalse(FileSystem.objects.filter(id=item_id).exists())

    def test_delete_channel_folder_cascades_to_ref_less_canvas(self):
        # Deleting a channel folder cascades into its ref-less canvas children, which must
        # bare-delete rather than raise in `_ensure_can_delete`.
        item_id = self._create_dashboard(path="MyChannel/MyCanvas")
        folder = FileSystem.objects.get(team=self.team, path="MyChannel", type="folder")

        response = self.client.delete(f"/api/projects/{self.team.id}/desktop_file_system/{folder.id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT, response.content)
        self.assertFalse(FileSystem.objects.filter(id=folder.id).exists())
        self.assertFalse(FileSystem.objects.filter(id=item_id).exists())
