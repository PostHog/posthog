from unittest.mock import MagicMock, patch


from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.instance_setting import set_instance_setting
from posthog.tasks.hog_functions import hog_function_state_transition
from posthog.tasks.test.utils_email_tests import mock_email_messages
from posthog.test.base import APIBaseTest


@patch("posthog.tasks.email.EmailMessage")
@patch("posthog.tasks.hog_functions.report_team_action")
class TestHogFunctionTasks(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        set_instance_setting("EMAIL_HOST", "fake_host")
        set_instance_setting("EMAIL_ENABLED", True)

    def test_tracks_events_regardless(self, mock_report_action: MagicMock, MockEmailMessage: MagicMock) -> None:
        hog_function = HogFunction.objects.create(name="Test", team=self.team)
        hog_function_state_transition(str(hog_function.id), 1)

        mock_report_action.assert_called_once_with(
            self.team,
            "hog function state changed",
            {
                "hog_function_id": str(hog_function.id),
                "hog_function_url": f"http://localhost:8000/project/{hog_function.team.id}/pipeline/destinations/hog-{str(hog_function.id)}",
                "state": 1,
            },
        )

    def test_send_fatal_plugin_error(self, mock_report_action: MagicMock, MockEmailMessage: MagicMock) -> None:
        with self.settings(EMAIL_ENABLED=True, EMAIL_HOST="localhost", SITE_URL="http://localhost:8000"):
            mocked_email_messages = mock_email_messages(MockEmailMessage)
            hog_function = HogFunction.objects.create(name="Test", team=self.team)

            hog_function_state_transition(str(hog_function.id), 0)  # Healthy state
            assert len(mocked_email_messages) == 0
            hog_function_state_transition(str(hog_function.id), 1)  # Degraded state
            assert len(mocked_email_messages) == 0
            hog_function_state_transition(str(hog_function.id), 2)  # Disabled temp state
            assert len(mocked_email_messages) == 1
            hog_function_state_transition(str(hog_function.id), 3)  # Disabled state
            assert len(mocked_email_messages) == 2

            assert (
                mocked_email_messages[0].subject
                == "[Alert] Destination 'Test' has been disabled in project 'Default project' due to high error rate"
            )
            assert mocked_email_messages[0].to == [
                {
                    "raw_email": "user1@posthog.com",
                    "recipient": "user1@posthog.com",
                },
            ]
