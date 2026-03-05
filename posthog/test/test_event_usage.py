from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework.test import APIRequestFactory

from posthog.event_usage import EventSource, _sanitize_header_value, get_event_source, report_user_action


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
                    "mcp_user_agent": None,
                    "mcp_client_name": None,
                    "mcp_client_version": None,
                    "mcp_protocol_version": None,
                },
            ),
            (
                "includes_mcp_user_agent_from_header",
                {
                    "Referer": "http://app.posthog.com/insights",
                    "X-Posthog-Session-Id": "sess-123",
                    "X-Posthog-Mcp-User-Agent": "posthog/cursor 1.0",
                },
                None,
                {
                    "source": "api",
                    "$current_url": "http://app.posthog.com/insights",
                    "$session_id": "sess-123",
                    "was_impersonated": False,
                    "mcp_user_agent": "posthog/cursor 1.0",
                    "mcp_client_name": None,
                    "mcp_client_version": None,
                    "mcp_protocol_version": None,
                },
            ),
            (
                "includes_mcp_client_info_from_headers",
                {
                    "X-Posthog-Mcp-Client-Name": "claude-code",
                    "X-Posthog-Mcp-Client-Version": "1.2.3",
                    "X-Posthog-Mcp-Protocol-Version": "2025-03-26",
                },
                None,
                {
                    "source": "api",
                    "$current_url": None,
                    "$session_id": None,
                    "was_impersonated": False,
                    "mcp_user_agent": None,
                    "mcp_client_name": "claude-code",
                    "mcp_client_version": "1.2.3",
                    "mcp_protocol_version": "2025-03-26",
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
                    "mcp_user_agent": None,
                    "mcp_client_name": None,
                    "mcp_client_version": None,
                    "mcp_protocol_version": None,
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
                    "mcp_user_agent": None,
                    "mcp_client_name": None,
                    "mcp_client_version": None,
                    "mcp_protocol_version": None,
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
                    "mcp_user_agent": None,
                    "mcp_client_name": None,
                    "mcp_client_version": None,
                    "mcp_protocol_version": None,
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


class TestGetEventSource(BaseTest):
    @parameterized.expand(
        [
            ("terraform", "posthog/terraform-provider 1.0", EventSource.TERRAFORM),
            ("wizard", "posthog/wizard 1.0", EventSource.WIZARD),
            ("posthog_code", "posthog/code 1.2.3", EventSource.POSTHOG_CODE),
            ("hog_dev_subdomain", "posthog/desktop.hog.dev 0.1.0", EventSource.POSTHOG_CODE),
            ("hog_dev_complex", "posthog/my-app.hog.dev", EventSource.POSTHOG_CODE),
            ("mcp_server", "posthog/mcp-server 1.0", EventSource.MCP),
            ("unknown_ua_falls_through_to_api", "some-random-agent/1.0", EventSource.API),
        ]
    )
    def test_get_event_source(self, _name, user_agent, expected):
        factory = APIRequestFactory()
        request = factory.get("/fake", HTTP_USER_AGENT=user_agent)
        assert get_event_source(request) == expected


class TestSanitizeHeaderValue(BaseTest):
    @parameterized.expand(
        [
            ("passthrough", "posthog/wizard 1.0", "posthog/wizard 1.0"),
            ("strips_control_chars", "agent\x00with\x1fnulls", "agentwithnulls"),
            ("truncates_to_max_length", "a" * 1500, "a" * 1000),
            ("strips_whitespace", "  spaces  ", "spaces"),
            ("empty_string_returns_none", "", None),
            ("whitespace_only_returns_none", " ", None),
            ("none_returns_none", None, None),
        ]
    )
    def test_sanitize_header_value(self, _name, input_value, expected):
        assert _sanitize_header_value(input_value) == expected
