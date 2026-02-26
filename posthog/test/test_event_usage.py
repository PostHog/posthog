from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.event_usage import report_user_action


class TestReportUserAction(BaseTest):
    @parameterized.expand(
        [
            ("no_request", None, {"key": "val"}, {"key": "val"}),
            (
                "request_no_properties",
                "mock_request",
                None,
                {"source": "api", "$current_url": "http://test", "$session_id": "sess1", "was_impersonated": False},
            ),
            (
                "request_with_properties",
                "mock_request",
                {"key": "val"},
                {
                    "source": "api",
                    "$current_url": "http://test",
                    "$session_id": "sess1",
                    "was_impersonated": False,
                    "key": "val",
                },
            ),
            (
                "explicit_properties_take_precedence",
                "mock_request",
                {"source": "terraform", "$current_url": "override"},
                {
                    "source": "terraform",
                    "$current_url": "override",
                    "$session_id": "sess1",
                    "was_impersonated": False,
                },
            ),
        ]
    )
    @patch("posthog.event_usage.posthoganalytics.capture")
    @patch("posthog.event_usage.get_request_analytics_properties")
    def test_report_user_action_request_parameter(
        self, _name, request_val, properties, expected_properties, mock_get_props, mock_capture
    ):
        mock_get_props.return_value = {
            "source": "api",
            "$current_url": "http://test",
            "$session_id": "sess1",
            "was_impersonated": False,
        }

        request_obj = MagicMock() if request_val == "mock_request" else None

        report_user_action(self.user, "test event", properties=properties, request=request_obj)

        mock_capture.assert_called_once()
        captured_props = mock_capture.call_args[1]["properties"]
        assert captured_props == expected_properties

        if request_obj is not None:
            mock_get_props.assert_called_once_with(request_obj)
        else:
            mock_get_props.assert_not_called()

    @patch("posthog.event_usage.posthoganalytics.capture")
    @patch("posthog.event_usage.get_request_analytics_properties")
    def test_user_derived_from_request_when_not_provided(self, mock_get_props, mock_capture):
        mock_get_props.return_value = {
            "source": "api",
            "$current_url": None,
            "$session_id": None,
            "was_impersonated": False,
        }
        mock_request = MagicMock()
        mock_request.user = self.user

        report_user_action(event="test event", request=mock_request)

        mock_capture.assert_called_once()
        assert mock_capture.call_args[1]["distinct_id"] == self.user.distinct_id

    @patch("posthog.event_usage.posthoganalytics.capture")
    def test_no_user_no_request_is_noop(self, mock_capture):
        report_user_action(event="test event")

        mock_capture.assert_not_called()
