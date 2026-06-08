from __future__ import annotations

from posthog.test.base import APIBaseTest

from django.db import IntegrityError

from rest_framework import status

from posthog.models.file_system.persisted_folder import PersistedFolder
from posthog.models.user import User


class _Base(APIBaseTest):
    def setUp(self) -> None:  # noqa: D401
        super().setUp()
        self.user_2: User = User.objects.create_and_join(self.organization, "rookie@posthog.com", None)


class TestPersistedFolderModel(_Base):
    def test_defaults_and_str(self) -> None:
        pf = PersistedFolder.objects.create(team=self.team, user=self.user, type=PersistedFolder.TYPE_HOME)

        assert pf.protocol == "products://"
        assert pf.path == ""
        assert "home" in str(pf)
        assert pf.id  # UUID auto-assigned

    def test_unique_constraint(self) -> None:
        PersistedFolder.objects.create(team=self.team, user=self.user, type=PersistedFolder.TYPE_HOME)
        with self.assertRaises(IntegrityError):
            PersistedFolder.objects.create(team=self.team, user=self.user, type=PersistedFolder.TYPE_HOME)


class TestPersistedFolderAPI(_Base):
    def test_create_and_upsert(self) -> None:
        # 1️⃣  First POST → creates
        rsp = self.client.post(
            f"/api/projects/{self.team.id}/persisted_folder/",
            {"type": "home", "path": "Root/Home", "protocol": "products://"},
            format="json",
        )
        assert rsp.status_code == status.HTTP_201_CREATED
        assert PersistedFolder.objects.count() == 1

        obj_id = rsp.data["id"]

        # 2️⃣  Second POST with same (team,user,type) → updates existing row
        rsp2 = self.client.post(
            f"/api/projects/{self.team.id}/persisted_folder/",
            {"type": "home", "path": "Root/Home/V2", "protocol": "products://"},
            format="json",
        )
        assert rsp2.status_code == status.HTTP_201_CREATED  # ModelViewSet still returns 201
        assert PersistedFolder.objects.count() == 1  # still just one row
        assert rsp2.data["id"] == obj_id  # unchanged PK
        assert rsp2.data["path"] == "Root/Home/V2"  # updated field persisted

    def test_list_returns_only_current_user(self) -> None:
        # Create folders for two different users
        PersistedFolder.objects.create(team=self.team, user=self.user, type="home", path="A", protocol="products://")
        PersistedFolder.objects.create(team=self.team, user=self.user_2, type="home", path="B", protocol="products://")

        rsp = self.client.get(f"/api/projects/{self.team.id}/persisted_folder/")
        assert rsp.status_code == status.HTTP_200_OK
        assert len(rsp.data["results"]) == 1
        assert rsp.data["results"][0]["path"] == "A"


class TestPersistedFolderSurface(_Base):
    def setUp(self) -> None:
        super().setUp()
        self.web_url = f"/api/projects/{self.team.id}/persisted_folder/"
        self.desktop_url = f"/api/projects/{self.team.id}/desktop_persisted_folder/"

    def test_same_type_coexists_across_surfaces(self) -> None:
        # The same `type` ("home") is NOT surface-exclusive: each surface keeps its own row.
        web = self.client.post(self.web_url, {"type": "home", "path": "Web home"}, format="json")
        desktop = self.client.post(self.desktop_url, {"type": "home", "path": "Desktop home"}, format="json")

        self.assertEqual(web.status_code, status.HTTP_201_CREATED)
        self.assertEqual(desktop.status_code, status.HTTP_201_CREATED)
        self.assertEqual(PersistedFolder.objects.filter(team=self.team, user=self.user, type="home").count(), 2)

        web_paths = {r["path"] for r in self.client.get(self.web_url).data["results"]}
        desktop_paths = {r["path"] for r in self.client.get(self.desktop_url).data["results"]}
        self.assertEqual(web_paths, {"Web home"})
        self.assertEqual(desktop_paths, {"Desktop home"})

    def test_web_create_stamps_web_surface(self) -> None:
        self.client.post(self.web_url, {"type": "home", "path": "Web home"}, format="json")
        self.assertEqual(PersistedFolder.objects.get(team=self.team, user=self.user, type="home").surface, "web")

    def test_desktop_create_stamps_desktop_surface(self) -> None:
        self.client.post(self.desktop_url, {"type": "home", "path": "Desktop home"}, format="json")
        self.assertEqual(PersistedFolder.objects.get(team=self.team, user=self.user, type="home").surface, "desktop")

    def test_web_upsert_matches_legacy_null_row(self) -> None:
        # A legacy row predates the surface column. A web upsert must update it in place rather
        # than insert a second row that would collide under the coalescing unique index.
        legacy = PersistedFolder.objects.create(
            team=self.team, user=self.user, type="home", path="Legacy", surface=None
        )

        rsp = self.client.post(self.web_url, {"type": "home", "path": "Updated"}, format="json")

        self.assertEqual(rsp.status_code, status.HTTP_201_CREATED, rsp.data)
        self.assertEqual(PersistedFolder.objects.filter(team=self.team, user=self.user, type="home").count(), 1)
        legacy.refresh_from_db()
        self.assertEqual(legacy.path, "Updated")
