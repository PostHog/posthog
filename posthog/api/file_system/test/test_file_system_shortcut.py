from datetime import timedelta

from posthog.test.base import APIBaseTest

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models import User
from posthog.models.file_system.file_system_shortcut import FileSystemShortcut

from products.access_control.backend.models.access_control import AccessControl
from products.dashboards.backend.models.dashboard import Dashboard
from products.product_analytics.backend.facade.models import Insight


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

    @parameterized.expand(
        [
            ("reorder", "reorder", "ordered_ids"),
            ("bulk_update", "bulk_update", "remove_ids"),
        ]
    )
    def test_rejects_foreign_user_shortcuts(self, _name: str, url_path: str, ids_field: str):
        other_user = self._create_user("other")
        foreign = FileSystemShortcut.objects.create(team=self.team, path="Foreign", type="t", user=other_user)

        response = self.client.post(
            f"/api/projects/{self.team.id}/file_system_shortcut/{url_path}/",
            {ids_field: [str(foreign.id)], "add": [{"path": "Logs", "type": "logs", "href": "/logs"}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
        self.assertIn(str(foreign.id), response.json()["unknown_ids"])
        foreign.refresh_from_db()
        self.assertEqual(foreign.order, 0)
        self.assertFalse(FileSystemShortcut.objects.filter(user=self.user).exists())

    def test_bulk_update_adds_removes_and_skips_duplicates(self):
        kept = FileSystemShortcut.objects.create(
            team=self.team, path="Dashboards", type="dashboard", href="/dashboard", user=self.user, order=3
        )
        removed = FileSystemShortcut.objects.create(
            team=self.team, path="Logs", type="logs", href="/logs", user=self.user, order=4
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/file_system_shortcut/bulk_update/",
            {
                "add": [
                    {"path": "Session replay", "type": "session_replay", "href": "/replay"},
                    {"path": "Dashboards", "type": "dashboard", "href": "/dashboard"},
                    {"path": "Feature flags", "type": "feature_flag", "href": "/feature_flags"},
                    {"path": "Feature flags", "type": "feature_flag", "href": "/feature_flags"},
                ],
                "remove_ids": [str(removed.id)],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual(
            [(row["path"], row["order"]) for row in response.json()],
            [("Dashboards", 3), ("Session replay", 4), ("Feature flags", 5)],
        )
        self.assertEqual(response.json()[0]["id"], str(kept.id))
        self.assertFalse(FileSystemShortcut.objects.filter(id=removed.id).exists())

    def test_reorder_response_excludes_retired_shortcuts(self):
        retired = FileSystemShortcut.objects.create(
            team=self.team, path="Old link", type="link", user=self.user, order=0
        )
        kept = FileSystemShortcut.objects.create(
            team=self.team, path="Dashboards", type="dashboard", user=self.user, order=1
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/file_system_shortcut/reorder/",
            {"ordered_ids": [str(kept.id), str(retired.id)]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual([row["id"] for row in response.json()], [str(kept.id)])

    def test_bulk_update_response_excludes_retired_shortcuts(self):
        FileSystemShortcut.objects.create(team=self.team, path="Old link", type="link", user=self.user, order=0)

        response = self.client.post(
            f"/api/projects/{self.team.id}/file_system_shortcut/bulk_update/",
            {"add": [{"path": "Dashboards", "type": "dashboard", "href": "/dashboard"}]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual([row["path"] for row in response.json()], ["Dashboards"])

    @parameterized.expand(
        [
            ("retrieve", "get", status.HTTP_404_NOT_FOUND, True),
            ("update", "patch", status.HTTP_404_NOT_FOUND, True),
            ("delete", "delete", status.HTTP_204_NO_CONTENT, False),
        ]
    )
    def test_retired_shortcut_is_hidden_except_from_delete(
        self, _name: str, method: str, expected_status: int, still_exists: bool
    ) -> None:
        retired = FileSystemShortcut.objects.create(team=self.team, path="Old link", type="link", user=self.user)

        response = getattr(self.client, method)(
            f"/api/projects/{self.team.id}/file_system_shortcut/{retired.pk}/", {"path": "Renamed"}, format="json"
        )

        self.assertEqual(response.status_code, expected_status)
        self.assertEqual(FileSystemShortcut.objects.filter(pk=retired.pk, path="Old link").exists(), still_exists)

    @parameterized.expand(
        [
            ("create", "", {"path": "Old link", "type": "link"}),
            ("bulk_update", "bulk_update/", {"add": [{"path": "Old link", "type": "link"}]}),
        ]
    )
    def test_rejects_new_shortcut_of_retired_type(self, _name: str, url_suffix: str, body: dict) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/file_system_shortcut/{url_suffix}", body, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
        self.assertFalse(FileSystemShortcut.objects.filter(type="link").exists())

    def test_reorder_rejects_empty_list(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/file_system_shortcut/reorder/",
            {"ordered_ids": []},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestFileSystemShortcutAccessLevels(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": "access_control", "name": "access_control"},
            {"key": "role_based_access", "name": "role_based_access"},
        ]
        self.organization.save()
        self.other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "testpass")

    def test_annotates_resolved_access_level_and_fetches_object_creator(self):
        mine = Dashboard.objects.create(team=self.team, name="Mine", created_by=self.user)
        theirs = Dashboard.objects.create(team=self.team, name="Theirs", created_by=self.other_user)
        FileSystemShortcut.objects.create(
            team=self.team, user=self.user, path="Mine", type="dashboard", ref=str(mine.pk)
        )
        FileSystemShortcut.objects.create(
            team=self.team, user=self.user, path="Theirs", type="dashboard", ref=str(theirs.pk)
        )
        AccessControl.objects.create(team=self.team, resource="dashboard", resource_id=None, access_level="none")

        response = self.client.get(f"/api/projects/{self.team.id}/file_system_shortcut/")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        levels = {item["path"]: item["user_access_level"] for item in response.json()["results"]}
        # Shortcut rows don't store the object's creator - it is resolved from the target model,
        # so the user's own dashboard stays accessible while the blocked one is marked "none"
        self.assertEqual(levels, {"Mine": "manager", "Theirs": "none"})

    def test_unresolved_refs_indistinguishable_from_blocked_objects(self):
        # Shortcuts accept arbitrary refs, so a guessed ref must not reveal via its access
        # level whether a protected object exists
        insight = Insight.objects.create(team=self.team, name="Real", created_by=self.other_user)
        FileSystemShortcut.objects.create(
            team=self.team, user=self.user, path="Real", type="insight", ref=insight.short_id
        )
        FileSystemShortcut.objects.create(
            team=self.team, user=self.user, path="Guessed", type="insight", ref="nonexistent"
        )
        AccessControl.objects.create(team=self.team, resource="insight", resource_id=None, access_level="none")

        response = self.client.get(f"/api/projects/{self.team.id}/file_system_shortcut/")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        levels = {item["path"]: item["user_access_level"] for item in response.json()["results"]}
        self.assertEqual(levels, {"Real": "none", "Guessed": "none"})
