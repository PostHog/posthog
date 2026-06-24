"""
Security: the agent slug is interpolated into the ingress routing URL, so it's
constrained to a strict slug at the model + serializer SlugField layers.
"""

from __future__ import annotations

from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

_DBS = {
    "default",
    "persons_db_writer",
    "persons_db_reader",
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
