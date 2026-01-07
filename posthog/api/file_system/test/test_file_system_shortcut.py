from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models.file_system.file_system_shortcut import FileSystemShortcut


class TestFileSystemShortcutAPI(APIBaseTest):
    def test_list_shortcuts_initially_empty(self):
        response = self.client.get(f"/api/projects/{self.team.id}/file_system_shortcut/")
        assert response.status_code == status.HTTP_200_OK, response.json()
        response_data = response.json()
        assert response_data["count"] == 0
        assert response_data["results"] == []

    def test_create_shortcut(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/file_system_shortcut/",
            {"path": "Document.txt", "type": "doc-file"},
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()

        response_data = response.json()
        assert "id" in response_data
        assert response_data["path"] == "Document.txt"
        assert response_data["type"] == "doc-file"

    def test_retrieve_shortcut(self):
        shortcut_obj = FileSystemShortcut.objects.create(
            team=self.team,
            path="RetrievedFile.txt",
            type="test-type",
            user=self.user,
        )
        response = self.client.get(f"/api/projects/{self.team.id}/file_system_shortcut/{shortcut_obj.pk}/")
        assert response.status_code == status.HTTP_200_OK, response.json()

        response_data = response.json()
        assert response_data["id"] == str(shortcut_obj.id)
        assert response_data["path"] == "RetrievedFile.txt"
        assert response_data["type"] == "test-type"

    def test_update_shortcut(self):
        shortcut_obj = FileSystemShortcut.objects.create(
            team=self.team, path="file.txt", type="old-type", user=self.user
        )

        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/file_system_shortcut/{shortcut_obj.pk}/",
            {"path": "newfile.txt", "type": "new-type"},
        )
        assert update_response.status_code == status.HTTP_200_OK, update_response.json()
        updated_data = update_response.json()
        assert updated_data["path"] == "newfile.txt"
        assert updated_data["type"] == "new-type"

        shortcut_obj.refresh_from_db()
        assert shortcut_obj.path == "newfile.txt"
        assert shortcut_obj.type == "new-type"

    def test_delete_shortcut(self):
        shortcut_obj = FileSystemShortcut.objects.create(team=self.team, path="file.txt", type="temp", user=self.user)
        delete_response = self.client.delete(f"/api/projects/{self.team.id}/file_system_shortcut/{shortcut_obj.pk}/")
        assert delete_response.status_code == status.HTTP_204_NO_CONTENT
        assert not FileSystemShortcut.objects.filter(pk=shortcut_obj.pk).exists()

    def test_shortcuts_scoped_to_user(self):
        user1 = self._create_user("tim")
        user2 = self._create_user("tom")
        FileSystemShortcut.objects.create(team=self.team, path="file-me.txt", type="temp", user=self.user)
        FileSystemShortcut.objects.create(team=self.team, path="file-tim.txt", type="temp", user=user1)
        FileSystemShortcut.objects.create(team=self.team, path="file-tom.txt", type="temp", user=user2)

        response = self.client.get(f"/api/projects/{self.team.id}/file_system_shortcut/")
        assert response.status_code == status.HTTP_200_OK, response.json()
        response_data = response.json()
        assert response_data["count"] == 1
