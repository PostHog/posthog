"""
#2 — first-revision create + bundle_uri.

A no-source `revisions-create` is the documented way to mint the first
revision. The serializer advertised `bundle_uri` with `default: ""` but the
field rejected a blank value, so the generated MCP tool (which ships the
default explicitly) hit "may not be blank". `bundle_uri` is now `allow_blank`
and the view fills the `fs://<slug>/` convention when it's left empty.
"""

from __future__ import annotations

from posthog.test.base import APIBaseTest

from rest_framework import status

from ..models import AgentApplication

_SPEC = {"models": {"mode": "manual", "models": [{"model": "anthropic/claude-haiku-4-5"}]}}


class TestRevisionCreateBundleUri(APIBaseTest):
    databases = {
        "default",
        "agent_platform_db_writer",
        "agent_platform_db_reader",
    }

    def setUp(self) -> None:
        super().setUp()
        self.application = AgentApplication.all_teams.create(
            team_id=self.team.id,
            slug="create-bundle-agent",
            name="Create bundle agent",
            description="",
        )
        self.url = f"/api/projects/{self.team.id}/agent_applications/{self.application.id}/revisions/"

    def test_omitted_bundle_uri_autopopulates_fs_slug(self) -> None:
        res = self.client.post(self.url, {"spec": _SPEC}, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        self.assertEqual(res.json()["bundle_uri"], "fs://create-bundle-agent/")

    def test_blank_bundle_uri_accepted_and_autopopulated(self) -> None:
        # The exact payload the generated MCP tool sends (default: "").
        res = self.client.post(self.url, {"spec": _SPEC, "bundle_uri": ""}, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        self.assertEqual(res.json()["bundle_uri"], "fs://create-bundle-agent/")

    def test_explicit_bundle_uri_preserved(self) -> None:
        res = self.client.post(self.url, {"spec": _SPEC, "bundle_uri": "fs://custom/"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        self.assertEqual(res.json()["bundle_uri"], "fs://custom/")
