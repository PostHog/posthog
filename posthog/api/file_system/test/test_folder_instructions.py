from typing import cast

from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.api.file_system.folder_instructions_service import FOLDER_INSTRUCTIONS_MAX_BYTES
from posthog.models import Organization, Team
from posthog.models.file_system.file_system import FileSystem
from posthog.models.file_system.folder_instructions import FileSystemFolderInstructions


class TestDesktopFolderInstructionsAPI(APIBaseTest):
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

    def _instructions_url(self, folder_id: str) -> str:
        return f"/api/projects/{self.team.id}/desktop_file_system/{folder_id}/instructions/"

    def test_get_instructions_when_none_exist_returns_404(self):
        folder_id = self._create_desktop_folder()
        response = self.client.get(self._instructions_url(folder_id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, response.json())

    def test_publish_first_version_then_get(self):
        folder_id = self._create_desktop_folder()

        publish = self.client.patch(
            self._instructions_url(folder_id),
            {"content": "# Campaigns\n\nQ1 marketing assets."},
        )
        self.assertEqual(publish.status_code, status.HTTP_200_OK, publish.json())
        self.assertEqual(publish.json()["version"], 1)
        self.assertEqual(publish.json()["is_latest"], True)
        self.assertEqual(publish.json()["content"], "# Campaigns\n\nQ1 marketing assets.")

        get = self.client.get(self._instructions_url(folder_id))
        self.assertEqual(get.status_code, status.HTTP_200_OK, get.json())
        self.assertEqual(get.json()["content"], "# Campaigns\n\nQ1 marketing assets.")

    def test_publish_second_version_increments_and_supersedes(self):
        folder_id = self._create_desktop_folder()
        self.client.patch(self._instructions_url(folder_id), {"content": "first"})
        second = self.client.patch(self._instructions_url(folder_id), {"content": "second"})

        self.assertEqual(second.status_code, status.HTTP_200_OK, second.json())
        self.assertEqual(second.json()["version"], 2)

        get = self.client.get(self._instructions_url(folder_id))
        self.assertEqual(get.json()["content"], "second")
        self.assertEqual(get.json()["version"], 2)

        rows = FileSystemFolderInstructions.objects.unscoped().filter(folder_id=folder_id).order_by("version")
        self.assertEqual([(r.version, r.is_latest) for r in rows], [(1, False), (2, True)])

    def test_versions_list_returns_history_newest_first(self):
        folder_id = self._create_desktop_folder()
        self.client.patch(self._instructions_url(folder_id), {"content": "v1"})
        self.client.patch(self._instructions_url(folder_id), {"content": "v2"})

        response = self.client.get(self._instructions_url(folder_id) + "versions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        versions = response.json()
        self.assertEqual([v["version"] for v in versions], [2, 1])
        # Version-history entries omit the markdown content (progressive disclosure).
        self.assertNotIn("content", versions[0])

    def test_publish_rejects_oversized_content(self):
        folder_id = self._create_desktop_folder()
        oversized = "x" * (FOLDER_INSTRUCTIONS_MAX_BYTES + 1)
        response = self.client.patch(self._instructions_url(folder_id), {"content": oversized})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())

    def test_optimistic_concurrency_conflict(self):
        folder_id = self._create_desktop_folder()
        self.client.patch(self._instructions_url(folder_id), {"content": "first"})

        # base_version 0 implies "no instructions yet", but version 1 already exists → 409.
        response = self.client.patch(self._instructions_url(folder_id), {"content": "stale", "base_version": 0})
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT, response.json())
        self.assertEqual(response.json()["current_version"], 1)

    def test_cannot_attach_instructions_to_non_folder(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/desktop_file_system/",
            {"path": "MyFolder/MyInsight", "type": "insight", "ref": "abc"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        item_id = response.json()["id"]

        response = self.client.patch(self._instructions_url(item_id), {"content": "nope"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())

    def test_soft_delete_hides_instructions(self):
        folder_id = self._create_desktop_folder()
        self.client.patch(self._instructions_url(folder_id), {"content": "to delete"})

        delete = self.client.delete(self._instructions_url(folder_id))
        self.assertEqual(delete.status_code, status.HTTP_204_NO_CONTENT)

        get = self.client.get(self._instructions_url(folder_id))
        self.assertEqual(get.status_code, status.HTTP_404_NOT_FOUND, get.json())

        # A subsequent publish starts a fresh version 1 (soft-deleted rows are excluded).
        republish = self.client.patch(self._instructions_url(folder_id), {"content": "again"})
        self.assertEqual(republish.status_code, status.HTTP_200_OK, republish.json())
        self.assertEqual(republish.json()["version"], 1)

    def test_delete_when_none_exist_returns_404(self):
        folder_id = self._create_desktop_folder()
        response = self.client.delete(self._instructions_url(folder_id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, response.json())

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

        response = self.client.patch(self._instructions_url(str(other_folder.id)), {"content": "leak"})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, response.json())

    def test_web_surface_has_no_instructions_action(self):
        folder = FileSystem.objects.create(
            team=self.team,
            path="WebFolder",
            depth=1,
            type="folder",
            surface="web",
        )
        response = self.client.get(f"/api/projects/{self.team.id}/file_system/{folder.id}/instructions/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, response.json())
