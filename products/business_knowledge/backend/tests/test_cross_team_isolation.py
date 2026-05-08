from posthog.test.base import BaseTest
from unittest.mock import AsyncMock

from asgiref.sync import async_to_sync

from posthog.models.organization import Organization
from posthog.models.project import Project
from posthog.models.team import Team

from products.business_knowledge.backend import logic
from products.business_knowledge.backend.logic import create_text_source
from products.business_knowledge.backend.models import KnowledgeChunk, KnowledgeDocument, KnowledgeSource

from ee.hogai.tools.search import SearchTool


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


class TestCrossTeamSearchToolIsolation(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        other_org = Organization.objects.create(name="other_org")
        other_project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=other_org)
        self.other_team = Team.objects.create(id=other_project.id, project=other_project, organization=other_org)

        create_text_source(
            team_id=self.team.id,
            created_by_id=self.user.id,
            name="Team A Knowledge",
            text="Team A has specific onboarding workflows and automation rules.",
        )
        create_text_source(
            team_id=self.other_team.id,
            created_by_id=None,
            name="Team B Knowledge",
            text="Team B uses different onboarding processes and manual steps.",
        )

    def _make_tool(self, team: Team) -> SearchTool:
        tool = SearchTool(
            team=team,
            user=self.user,
            state=None,
            config={},
            context_manager=AsyncMock(),
        )
        tool._has_business_knowledge = True
        return tool

    def test_search_tool_returns_only_own_team_results(self) -> None:
        tool = self._make_tool(self.team)
        result = async_to_sync(tool._search_business_knowledge)("onboarding")
        assert "Team A Knowledge" in result
        assert "Team B Knowledge" not in result

    def test_search_tool_other_team_sees_own_data(self) -> None:
        tool = self._make_tool(self.other_team)
        result = async_to_sync(tool._search_business_knowledge)("onboarding")
        assert "Team B Knowledge" in result
        assert "Team A Knowledge" not in result
