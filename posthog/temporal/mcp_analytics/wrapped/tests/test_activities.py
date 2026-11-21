from datetime import UTC, datetime

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.models.team import Team
from posthog.temporal.mcp_analytics.wrapped.activities import _generate, wrapped_team_ids

from products.event_definitions.backend.models.event_definition import EventDefinition
from products.mcp_analytics.backend.models import MCPAnalyticsWrapped


class TestWrappedTeamDiscovery(BaseTest):
    def _team(self, name: str, event: str, last_seen_at: datetime) -> Team:
        team = Team.objects.create(organization=self.organization, name=name)
        EventDefinition.objects.create(team=team, name=event, last_seen_at=last_seen_at)
        return team

    def test_only_projects_with_tool_calls_this_year(self) -> None:
        this_year = self._team("this year", "$mcp_tool_call", datetime(2026, 3, 1, tzinfo=UTC))
        self._team("last year", "$mcp_tool_call", datetime(2025, 12, 30, tzinfo=UTC))
        self._team("pageviews only", "$pageview", datetime(2026, 3, 1, tzinfo=UTC))

        assert wrapped_team_ids(2026) == [this_year.id]


class TestGenerateWrapped(ClickhouseTestMixin, BaseTest):
    def test_generating_a_project_stores_its_snapshot(self) -> None:
        assert _generate(self.team.id, 2026) == MCPAnalyticsWrapped.Status.INELIGIBLE

        assert MCPAnalyticsWrapped.objects.unscoped().filter(team=self.team, year=2026).exists()
