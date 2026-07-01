"""
Regression: AgentRevisionViewSet — nested routes accept slug for parent lookup.

The TeamAndOrgViewSetMixin auto-filters by every parent URL kwarg as a
literal value (e.g. `application_id="<slug>"`). AgentApplication uses a
UUID primary key, so a slug in the URL would otherwise blow up at the
queryset filter with "'<slug>' is not a valid UUID". `AgentRevisionViewSet`
overrides `parents_query_dict` to resolve slug → UUID via the existing
`_resolve_application` helper before the mixin's filter runs.

These tests assert the contract: revisions are reachable by **either**
the application id or the application slug, and a missing slug returns
404 cleanly.
"""

from __future__ import annotations

from posthog.test.base import APIBaseTest

from rest_framework import status

from ..models import AgentApplication, AgentRevision


class TestRevisionsSlugLookup(APIBaseTest):
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
        # Two revisions so a list call returns >0 and we can tell the slug
        # path is actually resolving the right application.
        self.revision_a = AgentRevision.all_teams.create(application=self.application, state="draft", spec={})
        self.revision_b = AgentRevision.all_teams.create(application=self.application, state="draft", spec={})

    def test_revisions_list_accepts_slug(self) -> None:
        resp = self.client.get(f"/api/projects/{self.team.id}/agent_applications/{self.application.slug}/revisions/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = {rev["id"] for rev in resp.json()["results"]}
        self.assertEqual(ids, {str(self.revision_a.id), str(self.revision_b.id)})

    def test_revisions_list_accepts_uuid(self) -> None:
        # Slug + UUID must reach the same revisions.
        resp = self.client.get(f"/api/projects/{self.team.id}/agent_applications/{self.application.id}/revisions/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = {rev["id"] for rev in resp.json()["results"]}
        self.assertEqual(ids, {str(self.revision_a.id), str(self.revision_b.id)})

    def test_revisions_list_unknown_slug_404s(self) -> None:
        # Used to 500 with a ValidationError before the slug-resolution
        # override landed. Now it 404s cleanly.
        resp = self.client.get(f"/api/projects/{self.team.id}/agent_applications/does-not-exist/revisions/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_revision_retrieve_via_slug(self) -> None:
        resp = self.client.get(
            f"/api/projects/{self.team.id}/agent_applications/{self.application.slug}/revisions/{self.revision_a.id}/"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.json()["id"], str(self.revision_a.id))

    def test_revisions_list_archived_application_404s(self) -> None:
        # Archived applications shouldn't be reachable by slug either —
        # the lookup queryset filters `archived=False`.
        self.application.archived = True
        self.application.save(update_fields=["archived"])
        resp = self.client.get(f"/api/projects/{self.team.id}/agent_applications/{self.application.slug}/revisions/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
