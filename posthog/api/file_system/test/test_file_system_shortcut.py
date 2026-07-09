from datetime import timedelta

import pytest
from posthog.test.base import APIBaseTest

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models import User
from posthog.models.file_system.file_system_shortcut import FileSystemShortcut

from products.dashboards.backend.models.dashboard import Dashboard
from products.product_analytics.backend.models.insight import Insight

from ee.models.rbac.access_control import AccessControl


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


class TestFileSystemShortcutSurface(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.web_url = f"/api/projects/{self.team.id}/file_system_shortcut/"
        self.desktop_url = f"/api/projects/{self.team.id}/desktop_file_system_shortcut/"

    def test_routes_serve_isolated_shortcuts(self):
        self.client.post(self.web_url, {"path": "Web pin", "type": "doc"})
        self.client.post(self.desktop_url, {"path": "Desktop pin", "type": "doc"})

        web_paths = {r["path"] for r in self.client.get(self.web_url).json()["results"]}
        desktop_paths = {r["path"] for r in self.client.get(self.desktop_url).json()["results"]}

        self.assertEqual(web_paths, {"Web pin"})
        self.assertEqual(desktop_paths, {"Desktop pin"})

    def test_web_create_stamps_web_surface(self):
        self.client.post(self.web_url, {"path": "Web pin", "type": "doc"})
        self.assertEqual(
            FileSystemShortcut.objects.get(team=self.team, path="Web pin").surface,
            "web",
        )

    def test_desktop_create_stamps_desktop_surface(self):
        self.client.post(self.desktop_url, {"path": "Desktop pin", "type": "doc"})
        self.assertEqual(
            FileSystemShortcut.objects.get(team=self.team, path="Desktop pin").surface,
            "desktop",
        )

    def test_legacy_null_shortcut_appears_on_web_route_only(self):
        FileSystemShortcut.objects.create(team=self.team, path="Legacy pin", type="doc", user=self.user, surface=None)

        web_paths = {r["path"] for r in self.client.get(self.web_url).json()["results"]}
        desktop_paths = {r["path"] for r in self.client.get(self.desktop_url).json()["results"]}

        self.assertIn("Legacy pin", web_paths)
        self.assertNotIn("Legacy pin", desktop_paths)

    def test_reorder_is_scoped_to_surface(self):
        web = FileSystemShortcut.objects.create(team=self.team, path="Web", type="t", user=self.user, surface="web")
        desktop = FileSystemShortcut.objects.create(
            team=self.team, path="Desktop", type="t", user=self.user, surface="desktop"
        )

        # A desktop reorder must not recognise (or touch) a web shortcut id.
        response = self.client.post(
            f"{self.desktop_url}reorder/",
            {"ordered_ids": [str(web.id)]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
        self.assertIn(str(web.id), response.json()["unknown_ids"])

        # But it accepts its own surface's shortcut.
        ok = self.client.post(
            f"{self.desktop_url}reorder/",
            {"ordered_ids": [str(desktop.id)]},
            format="json",
        )
        self.assertEqual(ok.status_code, status.HTTP_200_OK, ok.json())


@pytest.mark.ee
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
