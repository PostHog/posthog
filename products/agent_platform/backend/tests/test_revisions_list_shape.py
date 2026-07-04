from __future__ import annotations

from posthog.test.base import APIBaseTest

from rest_framework import status

from ..models import AgentApplication, AgentRevision


class TestRevisionsListShape(APIBaseTest):
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
        # A non-trivial spec so "omitted from the list" is a meaningful assertion.
        self.spec = {
            "tools": [{"name": "set_secret", "approval_policy": "always", "description": "x" * 500}],
            "skills": [],
            "triggers": [],
        }
        self.revision = AgentRevision.all_teams.create(application=self.application, state="draft", spec=self.spec)

    def test_list_omits_spec_but_keeps_navigation_metadata(self) -> None:
        resp = self.client.get(f"/api/projects/{self.team.id}/agent_applications/{self.application.slug}/revisions/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        row = resp.json()["results"][0]
        self.assertNotIn("spec", row)
        self.assertNotIn("skill_refs", row)
        self.assertEqual(row["id"], str(self.revision.id))
        self.assertEqual(row["state"], "draft")
        self.assertIn("bundle_sha256", row)

    def test_retrieve_still_returns_full_spec(self) -> None:
        resp = self.client.get(
            f"/api/projects/{self.team.id}/agent_applications/{self.application.slug}/revisions/{self.revision.id}/"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.json()["spec"], self.spec)
