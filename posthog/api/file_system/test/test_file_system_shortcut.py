from datetime import timedelta

from posthog.test.base import APIBaseTest

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.file_system.file_system_shortcut import FileSystemShortcut


class TestFileSystemShortcutAPI(APIBaseTest):
    def test_list_shortcuts_initially_empty(self):
        response = self.client.get(f"/api/projects/{self.team.id}/file_system_shortcut/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        response_data = response.json()
        self.assertEqual(response_data["count"], 0)
        self.assertEqual(response_data["results"], [])

    def test_create_shortcut(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/file_system_shortcut/",
            {"path": "Document.txt", "type": "doc-file"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())

        response_data = response.json()
        self.assertIn("id", response_data)
        self.assertEqual(response_data["path"], "Document.txt")
        self.assertEqual(response_data["type"], "doc-file")

    def test_retrieve_shortcut(self):
        shortcut_obj = FileSystemShortcut.objects.create(
            team=self.team,
            path="RetrievedFile.txt",
            type="test-type",
            user=self.user,
        )
        response = self.client.get(f"/api/projects/{self.team.id}/file_system_shortcut/{shortcut_obj.pk}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        response_data = response.json()
        self.assertEqual(response_data["id"], str(shortcut_obj.id))
        self.assertEqual(response_data["path"], "RetrievedFile.txt")
        self.assertEqual(response_data["type"], "test-type")

    def test_update_shortcut(self):
        shortcut_obj = FileSystemShortcut.objects.create(
            team=self.team, path="file.txt", type="old-type", user=self.user
        )

        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/file_system_shortcut/{shortcut_obj.pk}/",
            {"path": "newfile.txt", "type": "new-type"},
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK, update_response.json())
        updated_data = update_response.json()
        self.assertEqual(updated_data["path"], "newfile.txt")
        self.assertEqual(updated_data["type"], "new-type")

        shortcut_obj.refresh_from_db()
        self.assertEqual(shortcut_obj.path, "newfile.txt")
        self.assertEqual(shortcut_obj.type, "new-type")

    def test_delete_shortcut(self):
        shortcut_obj = FileSystemShortcut.objects.create(team=self.team, path="file.txt", type="temp", user=self.user)
        delete_response = self.client.delete(f"/api/projects/{self.team.id}/file_system_shortcut/{shortcut_obj.pk}/")
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(FileSystemShortcut.objects.filter(pk=shortcut_obj.pk).exists())

    def test_shortcuts_scoped_to_user(self):
        user1 = self._create_user("tim")
        user2 = self._create_user("tom")
        FileSystemShortcut.objects.create(team=self.team, path="file-me.txt", type="temp", user=self.user)
        FileSystemShortcut.objects.create(team=self.team, path="file-tim.txt", type="temp", user=user1)
        FileSystemShortcut.objects.create(team=self.team, path="file-tom.txt", type="temp", user=user2)

        response = self.client.get(f"/api/projects/{self.team.id}/file_system_shortcut/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        response_data = response.json()
        self.assertEqual(response_data["count"], 1)

    def test_list_shortcuts_ordering_by_created_at(self):
        older = FileSystemShortcut.objects.create(team=self.team, path="older.txt", type="t", user=self.user)
        newer = FileSystemShortcut.objects.create(team=self.team, path="newer.txt", type="t", user=self.user)
        FileSystemShortcut.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(days=1))

        response = self.client.get(
            f"/api/projects/{self.team.id}/file_system_shortcut/",
            {"ordering": "-created_at"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        ids = [row["id"] for row in response.json()["results"]]
        self.assertEqual(ids, [str(newer.id), str(older.id)])

    def test_default_list_orders_by_order_then_path(self):
        # Same order → alphabetical tie-break by path (pre-reorder behavior).
        a = FileSystemShortcut.objects.create(team=self.team, path="Apples", type="t", user=self.user, order=0)
        b = FileSystemShortcut.objects.create(team=self.team, path="Bananas", type="t", user=self.user, order=0)
        # Explicit order wins over alphabetical.
        z_first = FileSystemShortcut.objects.create(team=self.team, path="Zebra", type="t", user=self.user, order=-1)

        response = self.client.get(f"/api/projects/{self.team.id}/file_system_shortcut/")
        ids = [row["id"] for row in response.json()["results"]]
        self.assertEqual(ids, [str(z_first.id), str(a.id), str(b.id)])

    def test_create_appends_to_end_of_order(self):
        existing = FileSystemShortcut.objects.create(team=self.team, path="Existing", type="t", user=self.user, order=5)

        response = self.client.post(
            f"/api/projects/{self.team.id}/file_system_shortcut/",
            {"path": "Aardvark", "type": "t"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        new_id = response.json()["id"]
        self.assertEqual(response.json()["order"], 6)

        list_response = self.client.get(f"/api/projects/{self.team.id}/file_system_shortcut/")
        ids = [row["id"] for row in list_response.json()["results"]]
        self.assertEqual(ids, [str(existing.id), new_id])

    @parameterized.expand(
        [
            ("reverse", [2, 1, 0]),
            ("move_first_to_back", [1, 2, 0]),
            ("move_last_to_front", [2, 0, 1]),
            ("identity", [0, 1, 2]),
        ]
    )
    def test_reorder_sets_positions_and_returns_new_order(self, _name: str, permutation: list[int]):
        shortcuts = [
            FileSystemShortcut.objects.create(team=self.team, path=name, type="t", user=self.user, order=0)
            for name in ("One", "Two", "Three")
        ]
        ordered = [shortcuts[i] for i in permutation]

        response = self.client.post(
            f"/api/projects/{self.team.id}/file_system_shortcut/reorder/",
            {"ordered_ids": [str(s.id) for s in ordered]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual([row["id"] for row in response.json()], [str(s.id) for s in ordered])

        for expected_order, shortcut in enumerate(ordered):
            shortcut.refresh_from_db()
            self.assertEqual(shortcut.order, expected_order)

    def test_reorder_rejects_foreign_user_shortcuts(self):
        other_user = self._create_user("other")
        foreign = FileSystemShortcut.objects.create(team=self.team, path="Foreign", type="t", user=other_user)

        response = self.client.post(
            f"/api/projects/{self.team.id}/file_system_shortcut/reorder/",
            {"ordered_ids": [str(foreign.id)]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
        self.assertIn(str(foreign.id), response.json()["unknown_ids"])
        foreign.refresh_from_db()
        self.assertEqual(foreign.order, 0)

    def test_reorder_rejects_empty_list(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/file_system_shortcut/reorder/",
            {"ordered_ids": []},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
