from types import SimpleNamespace

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework.test import APIRequestFactory

from posthog.event_usage import (
    EventSource,
    get_event_source,
    get_mcp_properties,
    report_user_action,
    sanitize_header_value,
)


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
                    "$host": "app.posthog.com",
                    "$pathname": "/insights",
                    "$session_id": "sess-123",
                    "was_impersonated": False,
                    "mcp_user_agent": None,
                    "mcp_client_name": None,
                    "mcp_client_version": None,
                    "mcp_protocol_version": None,
                    "mcp_oauth_client_name": None,
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
                    "$host": "app.posthog.com",
                    "$pathname": "/insights",
                    "$session_id": "sess-123",
                    "was_impersonated": False,
                    "mcp_user_agent": "posthog/cursor 1.0",
                    "mcp_client_name": None,
                    "mcp_client_version": None,
                    "mcp_protocol_version": None,
                    "mcp_oauth_client_name": None,
                },
            ),
            (
                "includes_mcp_client_info_from_headers",
                {
                    "X-Posthog-Mcp-Client-Name": "claude-code",
                    "X-Posthog-Mcp-Client-Version": "1.2.3",
                    "X-Posthog-Mcp-Protocol-Version": "2025-03-26",
                    "X-Posthog-Mcp-Oauth-Client-Name": "Claude Code (posthog)",
                },
                None,
                {
                    "source": "api",
                    "$current_url": None,
                    "$host": None,
                    "$pathname": None,
                    "$session_id": None,
                    "was_impersonated": False,
                    "mcp_user_agent": None,
                    "mcp_client_name": "claude-code",
                    "mcp_client_version": "1.2.3",
                    "mcp_protocol_version": "2025-03-26",
                    "mcp_oauth_client_name": "Claude Code (posthog)",
                },
            ),
            (
                "merges_with_explicit_properties",
                {"Referer": "http://app.posthog.com/insights", "X-Posthog-Session-Id": "sess-123"},
                {"key": "val"},
                {
                    "source": "api",
                    "$current_url": "http://app.posthog.com/insights",
                    "$host": "app.posthog.com",
                    "$pathname": "/insights",
                    "$session_id": "sess-123",
                    "was_impersonated": False,
                    "mcp_user_agent": None,
                    "mcp_client_name": None,
                    "mcp_client_version": None,
                    "mcp_protocol_version": None,
                    "mcp_oauth_client_name": None,
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
                    "$host": "app.posthog.com",
                    "$pathname": "/insights",
                    "$session_id": "sess-123",
                    "was_impersonated": False,
                    "mcp_user_agent": None,
                    "mcp_client_name": None,
                    "mcp_client_version": None,
                    "mcp_protocol_version": None,
                    "mcp_oauth_client_name": None,
                },
            ),
            (
                "handles_missing_headers",
                {},
                {"key": "val"},
                {
                    "source": "api",
                    "$current_url": None,
                    "$host": None,
                    "$pathname": None,
                    "$session_id": None,
                    "was_impersonated": False,
                    "mcp_user_agent": None,
                    "mcp_client_name": None,
                    "mcp_client_version": None,
                    "mcp_protocol_version": None,
                    "mcp_oauth_client_name": None,
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
        assert captured_props == {**expected_properties, "$set_once": {"email": self.user.email}}

    @patch("posthog.event_usage.posthoganalytics.capture")
    def test_no_request_passes_properties_unchanged(self, mock_capture):
        report_user_action(self.user, "test event", properties={"key": "val"})

        mock_capture.assert_called_once()
        assert mock_capture.call_args[1]["properties"] == {"key": "val", "$set_once": {"email": self.user.email}}


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

    def test_web_via_session_authentication(self):
        from rest_framework.authentication import SessionAuthentication

        request = SimpleNamespace(META={}, successful_authenticator=SessionAuthentication())
        assert get_event_source(request) == EventSource.WEB

    def test_web_via_session_key_fallback(self):
        request = SimpleNamespace(META={}, session=SimpleNamespace(session_key="abc123"))
        assert get_event_source(request) == EventSource.WEB

    def test_api_when_session_is_dict(self):
        request = SimpleNamespace(META={}, session={})
        assert get_event_source(request) == EventSource.API

    def test_api_when_session_key_is_none(self):
        request = SimpleNamespace(META={}, session=SimpleNamespace(session_key=None))
        assert get_event_source(request) == EventSource.API


class TestGetMcpProperties(BaseTest):
    def test_extracts_all_mcp_headers(self):
        factory = APIRequestFactory()
        request = factory.get(
            "/fake",
            HTTP_X_POSTHOG_MCP_USER_AGENT="posthog/cursor 1.0",
            HTTP_X_POSTHOG_MCP_CLIENT_NAME="claude-code",
            HTTP_X_POSTHOG_MCP_CLIENT_VERSION="1.2.3",
            HTTP_X_POSTHOG_MCP_PROTOCOL_VERSION="2025-03-26",
            HTTP_X_POSTHOG_MCP_OAUTH_CLIENT_NAME="Claude Code (posthog)",
        )
        assert get_mcp_properties(request) == {
            "mcp_user_agent": "posthog/cursor 1.0",
            "mcp_client_name": "claude-code",
            "mcp_client_version": "1.2.3",
            "mcp_protocol_version": "2025-03-26",
            "mcp_oauth_client_name": "Claude Code (posthog)",
        }

    def test_returns_none_for_missing_headers(self):
        factory = APIRequestFactory()
        request = factory.get("/fake")
        assert get_mcp_properties(request) == {
            "mcp_user_agent": None,
            "mcp_client_name": None,
            "mcp_client_version": None,
            "mcp_protocol_version": None,
            "mcp_oauth_client_name": None,
        }


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
        assert sanitize_header_value(input_value) == expected
