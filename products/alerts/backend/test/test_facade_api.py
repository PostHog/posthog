from posthog.test.base import BaseTest

from posthog.models.team import Team

from products.alerts.backend.facade.api import insight_ids_with_enabled_alerts
from products.alerts.backend.test.insight_alerts import create_insight_alert


class TestInsightIdsWithEnabledAlerts(BaseTest):
    def test_returns_only_the_teams_insights_with_an_enabled_alert(self) -> None:
        enabled = create_insight_alert(self.team)
        disabled = create_insight_alert(self.team, enabled=False)
        other_team_alert = create_insight_alert(Team.objects.create(organization=self.organization))

        result = insight_ids_with_enabled_alerts(
            team_id=self.team.pk,
            insight_ids={enabled.insight_id, disabled.insight_id, other_team_alert.insight_id},
        )

        assert result == {enabled.insight_id}
