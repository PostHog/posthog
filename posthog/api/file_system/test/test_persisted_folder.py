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

        self.assertEqual(pf.protocol, "products://")
        self.assertEqual(pf.path, "")
        self.assertIn("home", str(pf))
        self.assertTrue(pf.id)  # UUID auto-assigned

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
        self.assertEqual(rsp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(PersistedFolder.objects.count(), 1)

        obj_id = rsp.data["id"]

        # 2️⃣  Second POST with same (team,user,type) → updates existing row
        rsp2 = self.client.post(
            f"/api/projects/{self.team.id}/persisted_folder/",
            {"type": "home", "path": "Root/Home/V2", "protocol": "products://"},
            format="json",
        )
        self.assertEqual(rsp2.status_code, status.HTTP_201_CREATED)  # ModelViewSet still returns 201
        self.assertEqual(PersistedFolder.objects.count(), 1)  # still just one row
        self.assertEqual(rsp2.data["id"], obj_id)  # unchanged PK
        self.assertEqual(rsp2.data["path"], "Root/Home/V2")  # updated field persisted

    def test_list_returns_only_current_user(self) -> None:
        # Create folders for two different users
        PersistedFolder.objects.create(team=self.team, user=self.user, type="home", path="A", protocol="products://")
        PersistedFolder.objects.create(team=self.team, user=self.user_2, type="home", path="B", protocol="products://")

        rsp = self.client.get(f"/api/projects/{self.team.id}/persisted_folder/")
        self.assertEqual(rsp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(rsp.data["results"]), 1)
        self.assertEqual(rsp.data["results"][0]["path"], "A")
