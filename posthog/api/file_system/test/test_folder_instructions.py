from typing import cast
from uuid import UUID

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

    def _folder_id_for_path(self, path: str) -> str:
        return str(FileSystem.objects.get(team=self.team, surface="desktop", path=path, type="folder").id)

    def test_new_channel_gets_blank_instructions_automatically(self):
        folder_id = self._create_desktop_folder()
        response = self.client.get(self._instructions_url(folder_id))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual(response.json()["version"], 1)
        self.assertEqual(response.json()["content"], "")
        self.assertEqual(response.json()["is_latest"], True)

    def test_nested_folder_creation_backfills_ancestor_instructions(self):
        self._create_desktop_folder("A/B/C")
        for path in ["A", "A/B", "A/B/C"]:
            folder_id = self._folder_id_for_path(path)
            response = self.client.get(self._instructions_url(folder_id))
            self.assertEqual(response.status_code, status.HTTP_200_OK, (path, response.json()))
            self.assertEqual(response.json()["content"], "")

    def test_creating_item_gives_parent_folder_blank_instructions(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/desktop_file_system/",
            {"path": "Parent/MyInsight", "type": "insight", "ref": "abc"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())

        parent_id = self._folder_id_for_path("Parent")
        get = self.client.get(self._instructions_url(parent_id))
        self.assertEqual(get.status_code, status.HTTP_200_OK, get.json())
        self.assertEqual(get.json()["content"], "")

    def test_publish_supersedes_blank_initial_version(self):
        folder_id = self._create_desktop_folder()

        publish = self.client.patch(
            self._instructions_url(folder_id),
            {"content": "# Campaigns\n\nQ1 marketing assets."},
        )
        self.assertEqual(publish.status_code, status.HTTP_200_OK, publish.json())
        # The auto-created blank version is 1, so the first real edit publishes version 2.
        self.assertEqual(publish.json()["version"], 2)
        self.assertEqual(publish.json()["content"], "# Campaigns\n\nQ1 marketing assets.")

        get = self.client.get(self._instructions_url(folder_id))
        self.assertEqual(get.json()["content"], "# Campaigns\n\nQ1 marketing assets.")
        self.assertEqual(get.json()["version"], 2)

    def test_publish_increments_and_supersedes(self):
        folder_id = self._create_desktop_folder()
        self.client.patch(self._instructions_url(folder_id), {"content": "first"})
        third = self.client.patch(self._instructions_url(folder_id), {"content": "second"})

        self.assertEqual(third.status_code, status.HTTP_200_OK, third.json())
        self.assertEqual(third.json()["version"], 3)

        get = self.client.get(self._instructions_url(folder_id))
        self.assertEqual(get.json()["content"], "second")

        rows = FileSystemFolderInstructions.objects.unscoped().filter(folder_id=UUID(folder_id)).order_by("version")
        self.assertEqual(
            [(r.version, r.content, r.is_latest) for r in rows],
            [(1, "", False), (2, "first", False), (3, "second", True)],
        )

    def test_versions_list_returns_history_newest_first(self):
        folder_id = self._create_desktop_folder()
        self.client.patch(self._instructions_url(folder_id), {"content": "v2"})
        self.client.patch(self._instructions_url(folder_id), {"content": "v3"})

        response = self.client.get(self._instructions_url(folder_id) + "versions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        body = response.json()
        versions = body["results"]
        self.assertEqual([v["version"] for v in versions], [3, 2, 1])
        # Version-history entries omit the markdown content (progressive disclosure).
        self.assertNotIn("content", versions[0])

    def test_publish_rejects_oversized_content(self):
        folder_id = self._create_desktop_folder()
        oversized = "x" * (FOLDER_INSTRUCTIONS_MAX_BYTES + 1)
        response = self.client.patch(self._instructions_url(folder_id), {"content": oversized})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())

    def test_optimistic_concurrency_conflict(self):
        folder_id = self._create_desktop_folder()  # auto-creates blank version 1

        response = self.client.patch(self._instructions_url(folder_id), {"content": "stale", "base_version": 99})
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
        # Folder created directly (not via the desktop API) has no auto-created instructions.
        folder = FileSystem.objects.create(
            team=self.team,
            path="OrphanFolder",
            depth=1,
            type="folder",
            surface="desktop",
        )
        response = self.client.delete(self._instructions_url(str(folder.id)))
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

    def test_personal_api_key_can_read_and_publish_instructions(self):
        folder_id = self._create_desktop_folder()
        key = self.create_personal_api_key_with_scopes(["file_system:write"])
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")

        url = self._instructions_url(folder_id)

        get = self.client.get(url)
        self.assertEqual(get.status_code, status.HTTP_200_OK, get.json())

        patch = self.client.patch(url, {"content": "hello"}, content_type="application/json")
        self.assertEqual(patch.status_code, status.HTTP_200_OK, patch.json())
        self.assertEqual(patch.json()["content"], "hello")

        versions = self.client.get(url + "versions/")
        self.assertEqual(versions.status_code, status.HTTP_200_OK, versions.json())

    def test_personal_api_key_with_read_only_scope_cannot_publish(self):
        folder_id = self._create_desktop_folder()
        key = self.create_personal_api_key_with_scopes(["file_system:read"])
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")

        url = self._instructions_url(folder_id)

        get = self.client.get(url)
        self.assertEqual(get.status_code, status.HTTP_200_OK, get.json())

        patch = self.client.patch(url, {"content": "hello"}, content_type="application/json")
        self.assertEqual(patch.status_code, status.HTTP_403_FORBIDDEN, patch.json())

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
