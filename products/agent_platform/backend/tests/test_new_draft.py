"""
Regression: AgentRevisionViewSet.new_draft must not seed a draft from a
revision belonging to a *different* application.

new_draft copies the source revision's `encrypted_env` (secrets) into the
new draft. Scoping the source lookup only by team would let an
`agents:write` caller create a draft under application A seeded from
application B's revision, siphoning B's secrets into a draft they then
edit/run. The source must belong to the same application as the draft.
"""

from __future__ import annotations

import json

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from rest_framework import status

from ..models import AgentApplication, AgentRevision


class TestNewDraftCrossApplication(APIBaseTest):
    databases = {
        "default",
        "persons_db_writer",
        "persons_db_reader",
        "agent_platform_db_writer",
        "agent_platform_db_reader",
    }

    def setUp(self) -> None:
        super().setUp()
        self.app_a = AgentApplication.all_teams.create(
            team_id=self.team.id,
            slug="app-a",
            name="App A",
            description="",
        )
        self.app_b = AgentApplication.all_teams.create(
            team_id=self.team.id,
            slug="app-b",
            name="App B",
            description="",
        )
        self.app_b_revision = AgentRevision.all_teams.create(
            application=self.app_b,
            team_id=self.team.id,
            state="live",
            spec={},
            bundle_uri="fs://app-b/",
            encrypted_env=json.dumps({"SECRET_KEY": "app-b-secret"}),
        )
        self.app_a_revision = AgentRevision.all_teams.create(
            application=self.app_a,
            team_id=self.team.id,
            state="live",
            spec={},
            bundle_uri="fs://app-a/",
            encrypted_env=json.dumps({"OWN_KEY": "app-a-secret"}),
        )

    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/agent_applications/{self.app_a.id}/revisions/new_draft/"

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_new_draft_rejects_source_from_other_application(self, mock_janitor: MagicMock) -> None:
        mock_janitor.return_value.clone_from.return_value = {}
        res = self.client.post(
            self._url(),
            {"application_id": str(self.app_a.id), "source_revision_id": str(self.app_b_revision.id)},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND, res.content)
        # No draft created, no secret copied, no janitor clone attempted.
        self.assertFalse(AgentRevision.all_teams.filter(application=self.app_a, state="draft").exists())
        mock_janitor.return_value.clone_from.assert_not_called()

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_new_draft_carries_secrets_from_same_application(self, mock_janitor: MagicMock) -> None:
        mock_janitor.return_value.clone_from.return_value = {}
        res = self.client.post(
            self._url(),
            {"application_id": str(self.app_a.id), "source_revision_id": str(self.app_a_revision.id)},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        draft_id = res.json()["revision"]["id"]
        draft = AgentRevision.all_teams.get(pk=draft_id)
        self.assertEqual(json.loads(draft.encrypted_env), {"OWN_KEY": "app-a-secret"})
        mock_janitor.return_value.clone_from.assert_called_once_with(str(draft.id), str(self.app_a_revision.id))
