from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

from posthog.models.organization import Organization
from posthog.models.project import Project
from posthog.models.scoping import team_scope
from posthog.models.team import Team

from products.business_knowledge.backend import logic
from products.business_knowledge.backend.logic import create_text_source
from products.business_knowledge.backend.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    SafetyVerdict,
    SourceType,
)


class TestCrossTeamIsolation(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        other_org = Organization.objects.create(name="other_org")
        other_project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=other_org)
        self.other_team = Team.objects.create(id=other_project.id, project=other_project, organization=other_org)

        create_text_source(
            team_id=self.team.id,
            created_by_id=self.user.id,
            name="Team A Docs",
            text="Our secret pricing model is tiered with enterprise discounts.",
        )
        create_text_source(
            team_id=self.other_team.id,
            created_by_id=None,
            name="Team B Docs",
            text="Team B has a completely different pricing approach.",
        )
        # Text starts `unknown` (classifier-gated); this test is about team
        # isolation, not safety, so model both teams' docs as classifier-cleared.
        for team_id in (self.team.id, self.other_team.id):
            with team_scope(team_id, canonical=True):
                KnowledgeDocument.objects.filter(team_id=team_id).update(safety_verdict=SafetyVerdict.SAFE)

    def test_search_only_returns_own_team_chunks(self) -> None:
        results_a = logic.search_knowledge(self.team.id, "pricing")
        results_b = logic.search_knowledge(self.other_team.id, "pricing")

        source_names_a = {r.source_name for r in results_a}
        source_names_b = {r.source_name for r in results_b}

        assert "Team A Docs" in source_names_a
        assert "Team B Docs" not in source_names_a
        assert "Team B Docs" in source_names_b
        assert "Team A Docs" not in source_names_b

    def test_has_ready_sources_scoped_to_team(self) -> None:
        assert logic.has_ready_sources(self.team.id) is True
        assert logic.has_ready_sources(self.other_team.id) is True

        KnowledgeChunk.objects.unscoped().filter(team=self.other_team).delete()
        KnowledgeDocument.objects.unscoped().filter(team=self.other_team).delete()
        KnowledgeSource.objects.unscoped().filter(team=self.other_team).delete()

        assert logic.has_ready_sources(self.team.id) is True
        assert logic.has_ready_sources(self.other_team.id) is False

    def _docs_team_source(self, name: str, text: str, url: str | None) -> None:
        source = create_text_source(team_id=self.other_team.id, created_by_id=None, name=name, text=text)
        with team_scope(self.other_team.id, canonical=True):
            KnowledgeDocument.objects.filter(source_id=source.id).update(
                safety_verdict=SafetyVerdict.SAFE, url=url or ""
            )
            if url:
                KnowledgeSource.objects.filter(id=source.id).update(source_type=SourceType.URL)

    @patch("products.business_knowledge.backend.logic.generate_embedding", side_effect=Exception("no embeddings"))
    def test_posthog_docs_search_reads_only_crawled_posthog_pages_of_the_docs_team(self, _embedding) -> None:
        self._docs_team_source("Crawled docs", "Pricing is usage based.", "https://posthog.com/docs/pricing")
        self._docs_team_source("Internal policy", "Internal pricing exceptions for enterprise.", None)
        self._docs_team_source("Other site", "Another vendor pricing page.", "https://example.com/pricing")

        with override_settings(BUSINESS_KNOWLEDGE_DOCS_TEAM_ID=self.other_team.id), team_scope(self.team.id):
            results = logic.search_posthog_docs("pricing")

        assert results is not None
        assert {r.source_name for r in results} == {"Crawled docs"}
        with override_settings(BUSINESS_KNOWLEDGE_DOCS_TEAM_ID=None):
            assert logic.search_posthog_docs("pricing") is None

    def test_ready_source_without_safety_cleared_content_is_not_searchable(self) -> None:
        KnowledgeDocument.objects.unscoped().filter(team=self.team).update(safety_verdict=SafetyVerdict.UNKNOWN)

        assert logic.has_ready_sources(self.team.id) is False
