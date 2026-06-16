"""
Slug ownership: the server mints a globally-unique slug on create, and only
teams on AGENT_PLATFORM_EXPLICIT_SLUG_TEAM_IDS may set one explicitly. Slugs
live in one global namespace (domain-mode ingress routing carries no team).
"""

from __future__ import annotations

from posthog.test.base import APIBaseTest

from django.test import override_settings

from rest_framework import status

from posthog.models import Organization, Team

from ..models import AgentApplication

_DBS = {
    "default",
    "agent_platform_db_writer",
    "agent_platform_db_reader",
}


class TestSlugMinting(APIBaseTest):
    databases = _DBS

    def _create(self, body: dict) -> tuple[int, dict]:
        resp = self.client.post(f"/api/projects/{self.team.id}/agent_applications/", body)
        return resp.status_code, resp.json()

    def test_non_allowlisted_team_gets_minted_slug_ignoring_input(self) -> None:
        status_code, body = self._create({"name": "Weekly digest", "slug": "weekly-digest"})
        self.assertEqual(status_code, status.HTTP_201_CREATED, body)
        # Explicit slug ignored; an opaque random slug is minted instead — no
        # name prefix, leading letter, lowercase alphanumeric, no dashes.
        self.assertNotIn("weekly", body["slug"])
        self.assertRegex(body["slug"], r"^[a-z][a-z0-9]{11}$")

    def test_minted_slug_without_input(self) -> None:
        status_code, body = self._create({"name": "Support bot"})
        self.assertEqual(status_code, status.HTTP_201_CREATED, body)
        self.assertNotIn("support", body["slug"])
        self.assertRegex(body["slug"], r"^[a-z][a-z0-9]{11}$")

    @override_settings(AGENT_PLATFORM_EXPLICIT_SLUG_TEAM_IDS=set())
    def test_minted_slugs_are_globally_unique_across_teams(self) -> None:
        # Two agents with the same name on the same team still get distinct slugs.
        _, first = self._create({"name": "Concierge"})
        _, second = self._create({"name": "Concierge"})
        self.assertNotEqual(first["slug"], second["slug"])

    def test_allowlisted_team_may_set_explicit_slug(self) -> None:
        with override_settings(AGENT_PLATFORM_EXPLICIT_SLUG_TEAM_IDS={self.team.id}):
            status_code, body = self._create({"name": "Agent concierge", "slug": "agent-concierge"})
        self.assertEqual(status_code, status.HTTP_201_CREATED, body)
        self.assertEqual(body["slug"], "agent-concierge")

    def test_explicit_slug_collision_is_a_clean_400(self) -> None:
        with override_settings(AGENT_PLATFORM_EXPLICIT_SLUG_TEAM_IDS={self.team.id}):
            self._create({"name": "Agent concierge", "slug": "agent-concierge"})
            status_code, body = self._create({"name": "Imposter", "slug": "agent-concierge"})
        self.assertEqual(status_code, status.HTTP_400_BAD_REQUEST, body)
        self.assertEqual(body["attr"], "slug")

    def test_explicit_slug_global_collision_across_teams(self) -> None:
        # A slug taken by another team blocks an allowlisted explicit set —
        # the namespace is global, not per-team.
        other_org = Organization.objects.create(name="other-org")
        other_team = Team.objects.create(organization=other_org, name="other-team")
        AgentApplication.all_teams.create(team_id=other_team.id, slug="taken", name="other")
        with override_settings(AGENT_PLATFORM_EXPLICIT_SLUG_TEAM_IDS={self.team.id}):
            status_code, body = self._create({"name": "Mine", "slug": "taken"})
        self.assertEqual(status_code, status.HTTP_400_BAD_REQUEST, body)
        self.assertEqual(body["attr"], "slug")
