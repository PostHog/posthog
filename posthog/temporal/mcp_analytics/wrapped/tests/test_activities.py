from datetime import UTC, datetime
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from posthog.models.team import Team
from posthog.temporal.mcp_analytics.wrapped.activities import _generate, wrapped_team_ids
from posthog.temporal.mcp_analytics.wrapped.constants import COMPUTE_FEATURE_FLAG

from products.event_definitions.backend.models.event_definition import EventDefinition
from products.mcp_analytics.backend.models import MCPAnalyticsWrapped

THIS_YEAR = datetime(2026, 3, 1, tzinfo=UTC)


class TestWrappedTeamDiscovery(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flagged_projects: set[str] = set()

    def _flag(self, key: str, distinct_id: str, *, groups: dict[str, str], **kwargs: Any) -> bool:
        return key == COMPUTE_FEATURE_FLAG and groups["project"] in self.flagged_projects

    def _team(self, name: str, event: str = "$mcp_tool_call", last_seen_at: datetime = THIS_YEAR) -> Team:
        team = Team.objects.create(organization=self.organization, name=name)
        EventDefinition.objects.create(team=team, name=event, last_seen_at=last_seen_at)
        return team

    def test_only_flagged_projects_with_tool_calls_this_year(self) -> None:
        flagged = self._team("flagged")
        self._team("not flagged")
        last_year = self._team("last year", last_seen_at=datetime(2025, 12, 30, tzinfo=UTC))
        pageviews_only = self._team("pageviews only", event="$pageview")
        self.flagged_projects = {str(team.uuid) for team in (flagged, last_year, pageviews_only)}

        with patch("posthoganalytics.feature_enabled", side_effect=self._flag):
            assert wrapped_team_ids(2026) == [flagged.id]

    def test_a_failed_flag_check_skips_the_project(self) -> None:
        self._team("flagged")

        with patch("posthoganalytics.feature_enabled", side_effect=RuntimeError("flags are down")):
            assert wrapped_team_ids(2026) == []


class TestGenerateWrapped(ClickhouseTestMixin, BaseTest):
    def test_generating_a_project_stores_its_snapshot(self) -> None:
        assert _generate(self.team.id, 2026) == MCPAnalyticsWrapped.Status.INELIGIBLE

        assert MCPAnalyticsWrapped.objects.unscoped().filter(team=self.team, year=2026).exists()
