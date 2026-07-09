"""
Regression: promote/archive run select_for_update inside transaction.atomic
against the agent_platform product DB.

Both actions lock the parent application row to serialize concurrent
promotes. Because the agent models live in a dedicated product DB, the
atomic block and the locking query must target that DB's writer alias
(`transaction.atomic(using=WRITER_DB)` + `.using(WRITER_DB)`), otherwise
they bind to `default` and 500 with "select_for_update cannot be used
outside of a transaction".
"""

from __future__ import annotations

from posthog.test.base import APIBaseTest

from rest_framework import status

from ..models import AgentApplication, AgentIdentityCredential, AgentRevision, AgentUser


class TestPromoteArchive(APIBaseTest):
    databases = {
        "default",
        "agent_platform_db_writer",
        "agent_platform_db_reader",
    }

    def setUp(self) -> None:
        super().setUp()
        self.application = AgentApplication.all_teams.create(
            team_id=self.team.id,
            slug="weekly-digest",
            name="Weekly digest",
            description="",
        )

    def _ready_revision(self) -> AgentRevision:
        # promote() requires a frozen bundle and `ready` state.
        return AgentRevision.all_teams.create(
            application=self.application,
            team_id=self.team.id,
            state="ready",
            spec={},
            bundle_sha256="a" * 64,
        )

    def _url(self, revision: AgentRevision, action: str) -> str:
        return (
            f"/api/projects/{self.team.id}/agent_applications/{self.application.id}/revisions/{revision.id}/{action}/"
        )

    def test_promote_sets_application_live_revision(self) -> None:
        revision = self._ready_revision()
        resp = self.client.post(self._url(revision, "promote"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        self.assertEqual(resp.json()["state"], "live")
        revision.refresh_from_db()
        self.application.refresh_from_db()
        self.assertEqual(revision.state, "live")
        self.assertEqual(self.application.live_revision_id, revision.id)

    def test_promote_archives_previous_live(self) -> None:
        first = self._ready_revision()
        self.client.post(self._url(first, "promote"))
        second = self._ready_revision()
        resp = self.client.post(self._url(second, "promote"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        first.refresh_from_db()
        self.application.refresh_from_db()
        self.assertEqual(first.state, "archived")
        self.assertEqual(self.application.live_revision_id, second.id)

    def test_archive_clears_live_pointer(self) -> None:
        revision = self._ready_revision()
        self.client.post(self._url(revision, "promote"))
        resp = self.client.post(self._url(revision, "archive"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        self.assertEqual(resp.json()["state"], "archived")
        revision.refresh_from_db()
        self.application.refresh_from_db()
        self.assertEqual(revision.state, "archived")
        self.assertIsNone(self.application.live_revision_id)

    def test_destroy_revokes_linked_credentials(self) -> None:
        """Archiving the application (soft-delete) revokes its users' active
        identity credentials — archive is terminal, so a retired agent holds no
        live bearers. Already-revoked rows are left as-is (only `active` flips)."""
        user = AgentUser.all_teams.create(
            team_id=self.team.id,
            application_id=self.application.id,
            principal_kind="slack",
            principal_id="U123",
        )
        active = AgentIdentityCredential.all_teams.create(
            team_id=self.team.id,
            application_id=self.application.id,
            agent_user_id=user.id,
            provider="posthog",
            encrypted_credentials="ciphertext",
            state="active",
        )
        already_revoked = AgentIdentityCredential.all_teams.create(
            team_id=self.team.id,
            application_id=self.application.id,
            agent_user_id=user.id,
            provider="github",
            encrypted_credentials="ciphertext",
            state="revoked",
        )

        resp = self.client.delete(f"/api/projects/{self.team.id}/agent_applications/{self.application.id}/")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT, resp.content)

        self.application.refresh_from_db()
        self.assertTrue(self.application.archived)

        active.refresh_from_db()
        self.assertEqual(active.state, "revoked")
        self.assertIsNotNone(active.revoked_at)

        already_revoked.refresh_from_db()
        self.assertEqual(already_revoked.state, "revoked")
