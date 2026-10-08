from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.models.file_system.file_system import FileSystem, split_path
from posthog.models.file_system.file_system_home_folder import FileSystemHomeFolder
from posthog.models.file_system.file_system_shortcut import FileSystemShortcut


class TestHomeFolder(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.first_name = "Alex Example"
        self.user.save(update_fields=["first_name"])
        self.url = f"/api/projects/{self.team.id}/file_system/home_folder/"

    def test_creates_public_folder_and_stars_it_once(self) -> None:
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()["path"], "Users/Alex Example")
        folder = FileSystem.objects.get(team=self.team, id=response.json()["id"])
        self.assertEqual(folder.depth, 2)
        self.assertTrue(FileSystem.objects.filter(team=self.team, path="Users", type="folder").exists())
        self.assertEqual(
            FileSystemShortcut.objects.get(team=self.team, user=self.user).ref,
            folder.path,
        )
        self.assertEqual(self.client.post(self.url).json(), response.json())
        self.assertEqual(FileSystem.objects.filter(team=self.team, path=folder.path).count(), 1)
        self.assertEqual(FileSystemShortcut.objects.filter(team=self.team, user=self.user).count(), 1)

    @parameterized.expand([("unstar",), ("delete",), ("rename",)])
    def test_does_not_restore_user_changes(self, change: str) -> None:
        original = self.client.post(self.url).json()
        FileSystemShortcut.objects.filter(team=self.team, user=self.user).delete()
        folder = FileSystem.objects.get(team=self.team, id=original["id"])
        if change == "delete":
            folder.delete()
        elif change == "rename":
            folder.path = "Research/My work"
            folder.save(update_fields=["path"])
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()["path"], None if change == "delete" else folder.path)
        self.assertFalse(FileSystemShortcut.objects.filter(team=self.team, user=self.user).exists())
        self.assertEqual(FileSystemHomeFolder.objects.for_team(self.team.id).filter(user=self.user).count(), 1)

    def test_adopts_an_existing_folder_without_starring_it(self) -> None:
        folder = FileSystem.objects.create(
            team=self.team, path="Users/Alex Example", type="folder", depth=2, created_by=self.user
        )
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()["id"], str(folder.id))
        self.assertFalse(FileSystemShortcut.objects.filter(team=self.team, user=self.user).exists())

    def test_same_name_users_get_separate_folders(self) -> None:
        first = self.client.post(self.url).json()
        second_user = self._create_user("alex.second@example.com", first_name="Alex Example")
        self.client.force_login(second_user)
        second = self.client.post(self.url)
        self.assertEqual(second.status_code, 200, second.json())
        self.assertEqual(second.json()["path"], "Users/Alex Example (1)")
        self.assertNotEqual(second.json()["id"], first["id"])
        self.assertEqual(FileSystemShortcut.objects.get(team=self.team, user=second_user).ref, second.json()["path"])

    @parameterized.expand([("Alex / Example",), ("Alex \\ Example",), ("A" * 150,), ("",)])
    def test_names_are_safe_folder_paths(self, name: str) -> None:
        self.user.first_name = name
        self.user.save(update_fields=["first_name"])
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(len(split_path(response.json()["path"])), 2)
        self.assertLessEqual(len(response.json()["path"]), 100)

    def test_home_folder_is_scoped_to_the_requested_team(self) -> None:
        first = self.client.post(self.url).json()
        other_team = Team.objects.create(organization=self.organization)
        response = self.client.post(f"/api/projects/{other_team.id}/file_system/home_folder/")
        self.assertEqual(response.status_code, 200, response.json())
        self.assertNotEqual(response.json()["id"], first["id"])
        self.assertTrue(FileSystem.objects.filter(team=other_team, id=response.json()["id"]).exists())
        foreign_team = Team.objects.create(organization=Organization.objects.create(name="Other project"))
        denied = self.client.post(f"/api/projects/{foreign_team.id}/file_system/home_folder/")
        self.assertEqual(denied.status_code, 403)
        self.assertFalse(FileSystemHomeFolder.objects.for_team(foreign_team.id).exists())

    def test_rolls_back_folder_creation_if_starring_fails(self) -> None:
        with patch.object(FileSystemShortcut.objects, "create", side_effect=RuntimeError("test failure")):
            response = self.client.post(self.url)
        self.assertEqual(response.status_code, 500)
        self.assertFalse(FileSystem.objects.filter(team=self.team, path="Users/Alex Example").exists())
        self.assertFalse(FileSystemHomeFolder.objects.for_team(self.team.id).filter(user=self.user).exists())
