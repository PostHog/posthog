from __future__ import annotations

from django.db import IntegrityError
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from posthog.models.file_system.persisted_folder import PersistedFolder
from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.user import User


# ------------------------------------------------------------------------------
#  Shared test-fixture
# ------------------------------------------------------------------------------
class _Base(TestCase):
    def setUp(self) -> None:  # noqa: D401
        self.org = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(name="Test Team", organization=self.org)

        self.user_1 = User.objects.create_user("alice@example.com", "pw", first_name="Alice")
        self.user_2 = User.objects.create_user("bob@example.com", "pw", first_name="Bob")

        # API client always authenticated as user-1 unless overwritten
        self.client = APIClient()
        self.client.force_authenticate(self.user_1)

        self.endpoint = "/api/persisted-folders/"


# ------------------------------------------------------------------------------
#  Model tests
# ------------------------------------------------------------------------------
class TestPersistedFolderModel(_Base):
    def test_defaults_and_str(self) -> None:
        pf = PersistedFolder.objects.create(team=self.team, user=self.user_1, type=PersistedFolder.TYPE_HOME)

        self.assertEqual(pf.protocol, "products://")
        self.assertEqual(pf.path, "")
        self.assertIn("home", str(pf))
        self.assertTrue(pf.id)  # UUID auto-assigned

    def test_unique_constraint(self) -> None:
        PersistedFolder.objects.create(team=self.team, user=self.user_1, type=PersistedFolder.TYPE_HOME)
        with self.assertRaises(IntegrityError):
            PersistedFolder.objects.create(team=self.team, user=self.user_1, type=PersistedFolder.TYPE_HOME)


# ------------------------------------------------------------------------------
#  API tests
# ------------------------------------------------------------------------------
class TestPersistedFolderAPI(_Base):
    def test_create_and_upsert(self) -> None:
        # 1️⃣  First POST → creates
        rsp = self.client.post(
            self.endpoint,
            {"type": "home", "path": "Root/Home"},
            format="json",
        )
        self.assertEqual(rsp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(PersistedFolder.objects.count(), 1)

        obj_id = rsp.data["id"]

        # 2️⃣  Second POST with same (team,user,type) → updates existing row
        rsp2 = self.client.post(
            self.endpoint,
            {"type": "home", "path": "Root/Home/V2"},
            format="json",
        )
        self.assertEqual(rsp2.status_code, status.HTTP_201_CREATED)  # ModelViewSet still returns 201
        self.assertEqual(PersistedFolder.objects.count(), 1)  # still just one row
        self.assertEqual(rsp2.data["id"], obj_id)  # unchanged PK
        self.assertEqual(rsp2.data["path"], "Root/Home/V2")  # updated field persisted

    def test_list_returns_only_current_user(self) -> None:
        # Create folders for two different users
        PersistedFolder.objects.create(team=self.team, user=self.user_1, type="home", path="A")
        PersistedFolder.objects.create(team=self.team, user=self.user_2, type="home", path="B")

        rsp = self.client.get(self.endpoint)
        self.assertEqual(rsp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(rsp.data["results"]), 1)
        self.assertEqual(rsp.data["results"][0]["path"], "A")
