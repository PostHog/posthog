from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from products.dashboards.backend.feature_flags import dashboard_customization_enabled


class TestDashboardFeatureFlags(SimpleTestCase):
    @patch("products.dashboards.backend.feature_flags.posthoganalytics.feature_enabled", return_value=True)
    def test_passes_user_email_to_feature_flag_evaluation(self, mock_feature_enabled) -> None:
        team = MagicMock(id=2, organization_id="organization-id")
        user = MagicMock(distinct_id="user-id", email="user@example.com")

        dashboard_customization_enabled(team=team, user=user)

        mock_feature_enabled.assert_called_once_with(
            "dashboard-customization",
            "user-id",
            person_properties={"email": "user@example.com"},
            groups={"organization": "organization-id", "project": "2"},
            group_properties={
                "organization": {"id": "organization-id"},
                "project": {"id": "2"},
            },
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
