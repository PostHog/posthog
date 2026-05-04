from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models import User
from posthog.tasks.user_identify import identify_task


class TestIdentifyTask(BaseTest):
    @patch("posthog.tasks.user_identify.posthoganalytics.capture")
    def test_captures_user_properties_when_user_exists(self, mock_capture) -> None:
        user = User.objects.create_user(email="exists@posthog.com", password="12345678", first_name="Test")

        identify_task(user_id=user.id)

        mock_capture.assert_called_once()
        kwargs = mock_capture.call_args.kwargs
        self.assertEqual(kwargs["distinct_id"], user.distinct_id)
        self.assertEqual(kwargs["event"], "update user properties")

    @patch("posthog.tasks.user_identify.posthoganalytics.capture")
    def test_returns_silently_when_user_was_deleted(self, mock_capture) -> None:
        user = User.objects.create_user(email="deleted@posthog.com", password="12345678", first_name="Test")
        user_id = user.id
        user.delete()

        identify_task(user_id=user_id)

        mock_capture.assert_not_called()
