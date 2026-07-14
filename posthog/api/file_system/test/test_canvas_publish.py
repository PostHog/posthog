from typing import TYPE_CHECKING, cast

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.apps import apps
from django.conf import settings

from rest_framework import status

from posthog.models.file_system.file_system import FileSystem
from posthog.models.oauth import OAuthApplication
from posthog.models.user import User
from posthog.temporal.oauth import (
    ARRAY_APP_CLIENT_ID_DEV,
    ARRAY_APP_CLIENT_ID_EU,
    ARRAY_APP_CLIENT_ID_US,
    create_oauth_access_token_for_user,
)

if TYPE_CHECKING:
    from products.tasks.backend.models import Task


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

    # Task models load via the app registry: this test lives outside the isolated
    # tasks product, so it can't import its internals (tach-enforced).
    def _create_task(self) -> "Task":
        Task = apps.get_model("tasks", "Task")
        return Task.objects.create(
            team=self.team,
            title="Generate canvas",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
        )

    def _thread_messages(self, task: "Task"):
        TaskThreadMessage = apps.get_model("tasks", "TaskThreadMessage")
        return TaskThreadMessage.objects.for_team(self.team.id).filter(task=task)

    def _authenticate_as_sandbox(self) -> None:
        """Swap session auth for a sandbox-app OAuth token — announcements only fire for
        requests bearing one. The app is created for every region client id because
        `create_oauth_access_token_for_user` resolves it by `get_instance_region()`."""
        for client_id in (ARRAY_APP_CLIENT_ID_DEV, ARRAY_APP_CLIENT_ID_US, ARRAY_APP_CLIENT_ID_EU):
            OAuthApplication.objects.get_or_create(
                client_id=client_id,
                defaults={
                    "name": "Array Test App",
                    "client_type": OAuthApplication.CLIENT_PUBLIC,
                    "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
                    "redirect_uris": "https://app.posthog.com/callback",
                    # RS256 is enforced by the `enforce_rs256_algorithm` DB constraint.
                    "algorithm": "RS256",
                },
            )
        token = create_oauth_access_token_for_user(self.user, self.team.id, scopes="full")
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    @patch("products.tasks.backend.facade.api.posthoganalytics.feature_enabled", return_value=True)
    def test_first_publish_from_task_announces_in_thread_once(self, _flag):
        task = self._create_task()
        item_id = self._create_dashboard(meta={"channelId": "chan-1"})
        self._authenticate_as_sandbox()

        self.client.patch(self._canvas_url(item_id), {"code": "v1"}, HTTP_X_POSTHOG_TASK_ID=str(task.id))

        messages = self._thread_messages(task)
        self.assertEqual(messages.count(), 1)
        message = messages.get()
        self.assertIsNone(message.author_id)
        self.assertEqual(
            message.content,
            f"[MyCanvas]({settings.SITE_URL}/code/canvas/chan-1/{item_id}) has been created",
        )

        # A second publish updates the canvas, it doesn't create it again.
        self.client.patch(self._canvas_url(item_id), {"code": "v2"}, HTTP_X_POSTHOG_TASK_ID=str(task.id))
        self.assertEqual(messages.count(), 1)

    @patch("products.tasks.backend.facade.api.posthoganalytics.feature_enabled", return_value=True)
    def test_announcement_links_via_parent_folder_when_meta_has_no_channel(self, _flag):
        task = self._create_task()
        item_id = self._create_dashboard()  # no channelId stamp — rows created before the app stamped it
        self._authenticate_as_sandbox()

        self.client.patch(self._canvas_url(item_id), {"code": "v1"}, HTTP_X_POSTHOG_TASK_ID=str(task.id))

        folder = FileSystem.objects.get(team=self.team, path="MyChannel", type="folder")
        message = self._thread_messages(task).get()
        self.assertTrue(message.content.startswith(f"[MyCanvas]({settings.SITE_URL}/code/canvas/{folder.id}/"))

    @patch("products.tasks.backend.facade.api.posthoganalytics.feature_enabled", return_value=True)
    def test_header_naming_someone_elses_task_stays_silent(self, _flag):
        # The header selects the announcement's thread; it must not let a publisher
        # plant agent messages in a task they didn't create.
        other = User.objects.create_and_join(self.organization, "other@posthog.com", None)
        Task = apps.get_model("tasks", "Task")
        task = Task.objects.create(
            team=self.team,
            title="Someone else's task",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=other,
        )
        item_id = self._create_dashboard()
        self._authenticate_as_sandbox()

        self.client.patch(self._canvas_url(item_id), {"code": "v1"}, HTTP_X_POSTHOG_TASK_ID=str(task.id))

        self.assertFalse(self._thread_messages(task).exists())

    @patch("products.tasks.backend.facade.api.posthoganalytics.feature_enabled", return_value=True)
    def test_session_authenticated_publish_with_header_stays_silent(self, _flag):
        # The header alone must not produce an agent announcement: a member setting it on
        # an ordinary (session-authenticated) publish of their own task would otherwise
        # forge a trusted-looking agent message. Only sandbox OAuth tokens qualify.
        task = self._create_task()
        item_id = self._create_dashboard()

        response = self.client.patch(self._canvas_url(item_id), {"code": "v1"}, HTTP_X_POSTHOG_TASK_ID=str(task.id))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(self._thread_messages(task).exists())

    def test_publish_without_task_attribution_stays_silent(self):
        item_id = self._create_dashboard()

        self.client.patch(self._canvas_url(item_id), {"code": "v1"})

        TaskThreadMessage = apps.get_model("tasks", "TaskThreadMessage")
        self.assertFalse(TaskThreadMessage.objects.for_team(self.team.id).exists())

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

    def test_delete_ref_less_non_dashboard_registered_row_still_refused_on_desktop(self):
        # The desktop ref-less exemption is scoped to `dashboard` canvases. Any other
        # registered type with no ref is still a data-integrity error we refuse to delete.
        file_obj = FileSystem.objects.create(
            team=self.team,
            path="MyChannel/OrphanInsight",
            type="insight",
            surface="desktop",
            created_by=self.user,
        )

        response = self.client.delete(f"/api/projects/{self.team.id}/desktop_file_system/{file_obj.id}/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        self.assertEqual(response.json()["detail"], "Cannot delete type 'insight' without a reference.")
        self.assertTrue(FileSystem.objects.filter(id=file_obj.id).exists())
