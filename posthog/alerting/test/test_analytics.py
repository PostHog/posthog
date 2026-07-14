from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from posthog.alerting.analytics import report_alert_action
from posthog.models.team.team import Team
from posthog.models.user import User


class TestReportAlertAction(SimpleTestCase):
    @patch("posthog.alerting.analytics.report_user_action")
    def test_reports_generic_event_with_config_type(self, mock_report_user_action: MagicMock) -> None:
        user = MagicMock(spec=User)
        team = MagicMock(spec=Team)
        request = MagicMock()

        report_alert_action(
            user=user,
            action="created",
            config_type="LogsAlertConfig",
            alert_id="alert-1",
            alert_name="High error rate",
            properties={"threshold_count": 10},
            team=team,
            request=request,
        )

        mock_report_user_action.assert_called_once_with(
            user,
            "alert created",
            {
                "threshold_count": 10,
                "alert_id": "alert-1",
                "alert_name": "High error rate",
                "config_type": "LogsAlertConfig",
            },
            team=team,
            request=request,
            analytics_props=None,
        )
