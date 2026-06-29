"""
Security: the agent slug is interpolated into the preview-proxy upstream URL, so
it's constrained to a strict slug at three layers — the model SlugField, the
serializer SlugField, and a defence-in-depth runtime check in preview_proxy that
guards against a slug which reached the DB without the Django validators (e.g. a
raw node-side write).
"""

from __future__ import annotations

from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from ..models import AgentApplication, AgentRevision

_DBS = {
    "default",
    "agent_platform_db_writer",
    "agent_platform_db_reader",
}


class TestSlugValidation(APIBaseTest):
    databases = _DBS

    @parameterized.expand(
        [
            ("space", "has spaces"),
            ("slash", "bad/slash"),
            ("dot", "dot.dot"),
            ("unicode", "ünïcode"),
        ]
    )
    def test_create_rejects_unsafe_slug(self, _name: str, slug: str) -> None:
        resp = self.client.post(
            f"/api/projects/{self.team.id}/agent_applications/",
            {"name": "X", "slug": slug},
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content)

    def test_create_accepts_valid_slug(self) -> None:
        resp = self.client.post(
            f"/api/projects/{self.team.id}/agent_applications/",
            {"name": "Weekly digest", "slug": "weekly-digest"},
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)

    @parameterized.expand(
        [
            # Slash → SSRF/path-traversal into the upstream URL.
            ("slash", "evil/path"),
            # Uppercase passes the model/serializer SlugField but the runtime
            # check is stricter (lowercase only) — proves it's an independent layer.
            ("uppercase", "MixedCase"),
        ]
    )
    def test_preview_proxy_rejects_unsafe_slug_in_db(self, _name: str, slug: str) -> None:
        # Simulate a write that bypassed the Django validators (e.g. raw node SQL):
        # .create() does not run model field validators.
        app = AgentApplication.all_teams.create(team_id=self.team.id, slug=slug, name="X")
        rev = AgentRevision.all_teams.create(application=app, team_id=self.team.id, state="draft", spec={})
        resp = self.client.post(
            f"/api/projects/{self.team.id}/agent_applications/{app.id}/preview-proxy/run?revision_id={rev.id}"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content)
        self.assertIn("unsafe", str(resp.content).lower())
