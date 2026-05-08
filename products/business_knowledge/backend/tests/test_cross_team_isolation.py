from posthog.test.base import BaseTest

from posthog.models.organization import Organization
from posthog.models.project import Project
from posthog.models.team import Team

from products.business_knowledge.backend import logic
from products.business_knowledge.backend.logic import create_text_source
from products.business_knowledge.backend.models import KnowledgeChunk, KnowledgeDocument, KnowledgeSource


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

        KnowledgeChunk.objects.filter(team=self.other_team).delete()
        KnowledgeDocument.objects.filter(team=self.other_team).delete()
        KnowledgeSource.objects.filter(team=self.other_team).delete()

        assert logic.has_ready_sources(self.team.id) is True
        assert logic.has_ready_sources(self.other_team.id) is False
