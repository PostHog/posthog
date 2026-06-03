from posthog.test.base import APIBaseTest
from unittest.mock import patch

from products.dashboards.backend.feature_flags import DASHBOARD_WIDGETS_FLAG, dashboard_widgets_enabled


class TestDashboardWidgetsFeatureFlag(APIBaseTest):
    @patch("products.dashboards.backend.feature_flags.posthoganalytics.feature_enabled", return_value=True)
    def test_uses_user_distinct_id_and_project_groups(self, feature_enabled_mock) -> None:
        self.user.distinct_id = "user-distinct-123"
        assert dashboard_widgets_enabled(team=self.team, user=self.user) is True

        feature_enabled_mock.assert_called_once_with(
            DASHBOARD_WIDGETS_FLAG,
            "user-distinct-123",
            groups={"organization": str(self.team.organization_id), "project": str(self.team.id)},
            group_properties={
                "organization": {"id": str(self.team.organization_id)},
                "project": {"id": str(self.team.id)},
            },
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )

    @patch("products.dashboards.backend.feature_flags.posthoganalytics.feature_enabled", return_value=False)
    def test_falls_back_to_team_uuid_without_user(self, feature_enabled_mock) -> None:
        assert dashboard_widgets_enabled(team=self.team, user=None) is False

        feature_enabled_mock.assert_called_once_with(
            DASHBOARD_WIDGETS_FLAG,
            str(self.team.uuid),
            groups={"organization": str(self.team.organization_id), "project": str(self.team.id)},
            group_properties={
                "organization": {"id": str(self.team.organization_id)},
                "project": {"id": str(self.team.id)},
            },
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
