from typing import TYPE_CHECKING, cast

from posthog.test.base import APIBaseTest

from django.apps import apps

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team
from posthog.models.file_system.file_system import FileSystem

if TYPE_CHECKING:
    from products.tasks.backend.models import Task


class TestDesktopFolderContextGenerationAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        # Staff gate mirrors the desktop/web file system beta gating.
        self.user.is_staff = True
        self.user.save()

    def _create_desktop_folder(self, path: str = "MyFolder") -> str:
        response = self.client.post(
            f"/api/projects/{self.team.id}/desktop_file_system/",
            {"path": path, "type": "folder"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        return cast(str, response.json()["id"])

    def _context_url(self, folder_id: str) -> str:
        return f"/api/projects/{self.team.id}/desktop_file_system/{folder_id}/context_generation/"

    def _instructions_url(self, folder_id: str) -> str:
        return f"/api/projects/{self.team.id}/desktop_file_system/{folder_id}/instructions/"

    def _create_task(self, team: Team | None = None) -> "Task":
        Task = apps.get_model("tasks", "Task")
        return Task.objects.create(
            team=team or self.team,
            title="Generate CONTEXT.md",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

    def test_get_returns_null_when_unset(self):
        folder_id = self._create_desktop_folder()
        response = self.client.get(self._context_url(folder_id))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual(response.json(), {"task_id": None})

    def test_put_sets_then_get_returns_it(self):
        folder_id = self._create_desktop_folder()
        task = self._create_task()

        put = self.client.put(self._context_url(folder_id), {"task_id": str(task.id)}, content_type="application/json")
        self.assertEqual(put.status_code, status.HTTP_200_OK, put.json())
        self.assertEqual(put.json(), {"task_id": str(task.id)})

        get = self.client.get(self._context_url(folder_id))
        self.assertEqual(get.json(), {"task_id": str(task.id)})

    def test_put_null_clears(self):
        folder_id = self._create_desktop_folder()
        task = self._create_task()
        self.client.put(self._context_url(folder_id), {"task_id": str(task.id)}, content_type="application/json")

        clear = self.client.put(self._context_url(folder_id), {"task_id": None}, content_type="application/json")
        self.assertEqual(clear.status_code, status.HTTP_200_OK, clear.json())
        self.assertEqual(clear.json(), {"task_id": None})
        self.assertEqual(self.client.get(self._context_url(folder_id)).json(), {"task_id": None})

    def test_put_overwrites_previous_value(self):
        folder_id = self._create_desktop_folder()
        first, second = self._create_task(), self._create_task()

        self.client.put(self._context_url(folder_id), {"task_id": str(first.id)}, content_type="application/json")
        self.client.put(self._context_url(folder_id), {"task_id": str(second.id)}, content_type="application/json")

        self.assertEqual(self.client.get(self._context_url(folder_id)).json(), {"task_id": str(second.id)})

    def test_publishing_new_instructions_version_clears_association(self):
        folder_id = self._create_desktop_folder()
        task = self._create_task()
        self.client.put(self._context_url(folder_id), {"task_id": str(task.id)}, content_type="application/json")

        publish = self.client.patch(self._instructions_url(folder_id), {"content": "# Generated"})
        self.assertEqual(publish.status_code, status.HTTP_200_OK, publish.json())

        self.assertEqual(self.client.get(self._context_url(folder_id)).json(), {"task_id": None})

    @parameterized.expand(
        [
            ("from_another_team", "foreign_task"),
            ("malformed", "not-a-uuid"),
        ]
    )
    def test_setting_invalid_task_id_is_rejected(self, _name: str, task_id: str):
        folder_id = self._create_desktop_folder()
        if task_id == "foreign_task":
            other_org = Organization.objects.create(name="Other Org")
            other_team = Team.objects.create(organization=other_org, name="Other Team")
            task_id = str(self._create_task(team=other_team).id)

        response = self.client.put(self._context_url(folder_id), {"task_id": task_id}, content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())

    def test_deleting_instructions_clears_association(self):
        folder_id = self._create_desktop_folder()
        # Publish instructions so DELETE has something to soft-delete, then mark a generation in progress.
        self.client.patch(self._instructions_url(folder_id), {"content": "# Generated"})
        task = self._create_task()
        self.client.put(self._context_url(folder_id), {"task_id": str(task.id)}, content_type="application/json")

        delete = self.client.delete(self._instructions_url(folder_id))
        self.assertEqual(delete.status_code, status.HTTP_204_NO_CONTENT, delete.content)

        self.assertEqual(self.client.get(self._context_url(folder_id)).json(), {"task_id": None})

    def test_cannot_access_folder_from_another_team(self):
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        other_folder = FileSystem.objects.create(
            team=other_team,
            path="Secret",
            depth=1,
            type="folder",
            surface="desktop",
        )

        get = self.client.get(self._context_url(str(other_folder.id)))
        self.assertEqual(get.status_code, status.HTTP_404_NOT_FOUND, get.json())

        task = self._create_task()
        put = self.client.put(
            self._context_url(str(other_folder.id)), {"task_id": str(task.id)}, content_type="application/json"
        )
        self.assertEqual(put.status_code, status.HTTP_404_NOT_FOUND, put.json())

    def test_personal_api_key_can_read_and_set_context_generation(self):
        folder_id = self._create_desktop_folder()
        task = self._create_task()
        key = self.create_personal_api_key_with_scopes(["file_system:write"])
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")

        get = self.client.get(self._context_url(folder_id))
        self.assertEqual(get.status_code, status.HTTP_200_OK, get.json())

        put = self.client.put(self._context_url(folder_id), {"task_id": str(task.id)}, content_type="application/json")
        self.assertEqual(put.status_code, status.HTTP_200_OK, put.json())
        self.assertEqual(put.json(), {"task_id": str(task.id)})

    def test_personal_api_key_with_read_only_scope_cannot_set(self):
        folder_id = self._create_desktop_folder()
        task = self._create_task()
        key = self.create_personal_api_key_with_scopes(["file_system:read"])
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")

        get = self.client.get(self._context_url(folder_id))
        self.assertEqual(get.status_code, status.HTTP_200_OK, get.json())

        put = self.client.put(self._context_url(folder_id), {"task_id": str(task.id)}, content_type="application/json")
        self.assertEqual(put.status_code, status.HTTP_403_FORBIDDEN, put.json())

    def test_must_be_a_folder(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/desktop_file_system/",
            {"path": "MyFolder/MyInsight", "type": "insight", "ref": "abc"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        item_id = response.json()["id"]

        get = self.client.get(self._context_url(item_id))
        self.assertEqual(get.status_code, status.HTTP_400_BAD_REQUEST, get.json())
