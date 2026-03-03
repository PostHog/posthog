from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework.test import APIRequestFactory

from posthog.event_usage import report_user_action


class TestReportUserAction(BaseTest):
    @parameterized.expand(
        [
            (
                "includes_all_request_properties",
                {"Referer": "http://app.posthog.com/insights", "X-Posthog-Session-Id": "sess-123"},
                None,
                {
                    "source": "api",
                    "$current_url": "http://app.posthog.com/insights",
                    "$session_id": "sess-123",
                    "was_impersonated": False,
                },
            ),
            (
                "merges_with_explicit_properties",
                {"Referer": "http://app.posthog.com/insights", "X-Posthog-Session-Id": "sess-123"},
                {"key": "val"},
                {
                    "source": "api",
                    "$current_url": "http://app.posthog.com/insights",
                    "$session_id": "sess-123",
                    "was_impersonated": False,
                    "key": "val",
                },
            ),
            (
                "explicit_properties_take_precedence",
                {"Referer": "http://app.posthog.com/insights", "X-Posthog-Session-Id": "sess-123"},
                {"source": "terraform", "$current_url": "override"},
                {
                    "source": "terraform",
                    "$current_url": "override",
                    "$session_id": "sess-123",
                    "was_impersonated": False,
                },
            ),
            (
                "handles_missing_headers",
                {},
                {"key": "val"},
                {
                    "source": "api",
                    "$current_url": None,
                    "$session_id": None,
                    "was_impersonated": False,
                    "key": "val",
                },
            ),
        ]
    )
    @patch("posthog.event_usage.posthoganalytics.capture")
    def test_request_properties_reach_capture(
        self, _name, headers, explicit_properties, expected_properties, mock_capture
    ):
        factory = APIRequestFactory()
        request = factory.get("/fake", headers=headers)

        report_user_action(self.user, "test event", properties=explicit_properties, request=request)

        mock_capture.assert_called_once()
        captured_props = mock_capture.call_args[1]["properties"]
        assert captured_props == expected_properties

    @patch("posthog.event_usage.posthoganalytics.capture")
    def test_no_request_passes_properties_unchanged(self, mock_capture):
        report_user_action(self.user, "test event", properties={"key": "val"})

        mock_capture.assert_called_once()
        assert mock_capture.call_args[1]["properties"] == {"key": "val"}

    @patch("posthog.event_usage.posthoganalytics.capture")
    def test_user_derived_from_request_when_not_provided(self, mock_capture):
        factory = APIRequestFactory()
        request = factory.get("/fake")
        request.user = self.user

        report_user_action(None, "test event", request=request)

        mock_capture.assert_called_once()
        assert mock_capture.call_args[1]["distinct_id"] == self.user.distinct_id

    @patch("posthog.event_usage.posthoganalytics.capture")
    def test_no_user_no_request_is_noop(self, mock_capture):
        report_user_action(None, "test event")

        mock_capture.assert_not_called()
