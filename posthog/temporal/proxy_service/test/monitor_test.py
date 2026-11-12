import ipaddress
from urllib.parse import urlparse

import pytest
import time_machine
from unittest.mock import MagicMock, Mock, call, patch

from django.test import SimpleTestCase, TestCase

import requests
from parameterized import parameterized

from posthog.models import Organization, ProxyRecord
from posthog.security.pinned_requests import SSRFBlockedError
from posthog.security.url_validation import PinnedUrlVerdict
from posthog.temporal.proxy_service.cloudflare import (
    CustomHostname,
    CustomHostnameSSL,
    CustomHostnameSSLStatus,
    CustomHostnameStatus,
)
from posthog.temporal.proxy_service.monitor import (
    CAPTURE_V1_PROBE_TIMEOUT_S,
    PROXY_LIVE_CHECK_TIMEOUT_S,
    CheckActivityInput,
    _check_cloudflare_certificate_status,
    check_proxy_is_live,
)


def _capture_v1_rejection() -> Mock:
    return Mock(status_code=400, json=Mock(return_value={"error": "missing_required_headers"}))


def _non_capture_response(status_code: int) -> Mock:
    return Mock(status_code=status_code, json=Mock(side_effect=ValueError("not JSON")))


def _respond_by_path(v0: object, analytics: object = None, ai: object = None):
    """A `pinned_request` side effect keyed by path, since the two v1 probes run in parallel."""
    by_path = {
        "/i/v0/e/": v0,
        "/i/v1/analytics/events": analytics or _capture_v1_rejection(),
        "/i/v1/ai/events": ai or _capture_v1_rejection(),
    }

    def respond(_method: str, url: str, **_kwargs):
        outcome = by_path[urlparse(url).path]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return respond


def _serve_cert(mock_ssl_context: Mock, not_after: str) -> None:
    mock_socket = Mock()
    mock_socket.getpeercert.return_value = {"notAfter": not_after}
    mock_wrapped_socket = Mock()
    mock_wrapped_socket.__enter__ = Mock(return_value=mock_socket)
    mock_wrapped_socket.__exit__ = Mock(return_value=None)
    mock_ssl_context.return_value.wrap_socket.return_value = mock_wrapped_socket


class TestCheckProxyIsLive(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.proxy_record = ProxyRecord.objects.create(
            organization=self.organization, domain="us.i.posthog.com", status="active"
        )
        self.input = CheckActivityInput(proxy_record_id=self.proxy_record.id)

    @pytest.mark.asyncio
    @patch("posthog.temporal.proxy_service.monitor.get_record")
    async def test_check_proxy_is_live_success_live(self, mock_get_record):
        """Live test against us.i.posthog.com"""
        mock_get_record.return_value = self.proxy_record

        result = await check_proxy_is_live(self.input)

        # Should succeed without errors or warnings
        self.assertEqual(result.errors, [])
        self.assertEqual(result.warnings, [])

    @pytest.mark.asyncio
    @time_machine.travel("2024-01-16 10:00:00", tick=False)  # Frozen at Jan 16, cert expires Feb 15 (30 days later)
    @patch("posthog.temporal.proxy_service.monitor.socket.create_connection")
    @patch("posthog.temporal.proxy_service.monitor.ssl.create_default_context")
    @patch("posthog.temporal.proxy_service.monitor.pinned_request")
    @patch("posthog.temporal.proxy_service.monitor.get_record")
    async def test_check_proxy_is_live_success_mocked(
        self, mock_get_record, mock_post, mock_ssl_context, mock_create_connection
    ):
        """Test successful proxy check with mocked dependencies"""
        mock_get_record.return_value = self.proxy_record

        # Mock successful HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_post.side_effect = _respond_by_path(mock_response)

        # Mock the raw socket the cert fetch opens so no real network connection is made
        mock_create_connection.return_value = MagicMock()

        # Mock SSL certificate check with fixed future date (20 days from frozen time)
        mock_cert = {"notAfter": "Feb  5 10:00:00 2024 GMT"}
        mock_socket = Mock()
        mock_socket.getpeercert.return_value = mock_cert

        mock_context = Mock()
        mock_wrapped_socket = Mock()
        mock_wrapped_socket.__enter__ = Mock(return_value=mock_socket)
        mock_wrapped_socket.__exit__ = Mock(return_value=None)
        mock_context.wrap_socket.return_value = mock_wrapped_socket
        mock_ssl_context.return_value = mock_context

        result = await check_proxy_is_live(self.input)

        # pinned_request carries the security boundary: it validates the host, pins the address it
        # validated, and never follows a redirect (see check_proxy_is_live). timeout stops a
        # malicious domain hanging us.
        self.assertCountEqual(
            mock_post.call_args_list,
            [
                call(
                    "POST",
                    f"https://{self.proxy_record.domain}/i/v0/e/",
                    json={"event": "test", "api_key": "test", "distinct_id": "test"},
                    timeout=PROXY_LIVE_CHECK_TIMEOUT_S,
                ),
                call(
                    "POST",
                    f"https://{self.proxy_record.domain}/i/v1/analytics/events",
                    headers={"Authorization": "Bearer phc_probe"},
                    json={},
                    timeout=CAPTURE_V1_PROBE_TIMEOUT_S,
                ),
                call(
                    "POST",
                    f"https://{self.proxy_record.domain}/i/v1/ai/events",
                    headers={"Authorization": "Bearer phc_probe"},
                    json={},
                    timeout=CAPTURE_V1_PROBE_TIMEOUT_S,
                ),
            ],
        )

        self.assertEqual(result.errors, [])
        self.assertEqual(result.warnings, [])

    @parameterized.expand(
        [
            ("not_routed", _non_capture_response(404), "got 404"),
            ("upstream_error", _non_capture_response(502), "got 502"),
            ("redirect", _non_capture_response(301), "got 301"),
            ("blocked_in_front_of_capture", _non_capture_response(403), "got 403"),
            (
                "deeply_nested_body",
                Mock(status_code=200, json=Mock(side_effect=RecursionError("too deep"))),
                "got 200",
            ),
            ("other_json_error", Mock(status_code=401, json=Mock(return_value={"error": "unauthorized"})), "got 401"),
            (
                "authorization_dropped",
                Mock(status_code=401, json=Mock(return_value={"error": "missing_authorization"})),
                "got 401",
            ),
            ("connection_error", requests.exceptions.ConnectionError("refused"), "ConnectionError"),
            ("ssrf_blocked", SSRFBlockedError("private address"), "SSRFBlockedError"),
        ]
    )
    @pytest.mark.asyncio
    @time_machine.travel("2024-01-16 10:00:00", tick=False)
    @patch("posthog.temporal.proxy_service.monitor.socket.create_connection")
    @patch("posthog.temporal.proxy_service.monitor.ssl.create_default_context")
    @patch("posthog.temporal.proxy_service.monitor.pinned_request")
    @patch("posthog.temporal.proxy_service.monitor.get_record")
    async def test_check_proxy_is_live_reports_unrouted_v1_capture_and_still_checks_cert(
        self, _name, v1_response, reason, mock_get_record, mock_post, mock_ssl_context, mock_create_connection
    ):
        mock_get_record.return_value = self.proxy_record
        mock_post.side_effect = _respond_by_path(
            Mock(status_code=200, raise_for_status=Mock(return_value=None)), analytics=v1_response
        )
        mock_create_connection.return_value = MagicMock()
        _serve_cert(mock_ssl_context, not_after="Jan 25 10:00:00 2024 GMT")

        result = await check_proxy_is_live(self.input)

        self.assertEqual(result.errors, ["Live proxy certificate is expiring soon"])
        self.assertEqual(
            result.warnings,
            [f"Proxy does not forward /i/v1/analytics/events ({reason}); v1 SDKs send events there"],
        )

    @pytest.mark.asyncio
    @time_machine.travel("2024-01-16 10:00:00", tick=False)
    @patch("posthog.temporal.proxy_service.monitor.socket.create_connection")
    @patch("posthog.temporal.proxy_service.monitor.ssl.create_default_context")
    @patch("posthog.temporal.proxy_service.monitor.pinned_request")
    @patch("posthog.temporal.proxy_service.monitor.get_record")
    async def test_check_proxy_is_live_reports_unrouted_v1_ai_capture(
        self, mock_get_record, mock_post, mock_ssl_context, mock_create_connection
    ):
        mock_get_record.return_value = self.proxy_record
        mock_post.side_effect = _respond_by_path(
            Mock(status_code=200, raise_for_status=Mock(return_value=None)), ai=_non_capture_response(404)
        )
        mock_create_connection.return_value = MagicMock()
        _serve_cert(mock_ssl_context, not_after="Feb  5 10:00:00 2024 GMT")

        result = await check_proxy_is_live(self.input)

        self.assertEqual(result.errors, [])
        self.assertEqual(
            result.warnings,
            ["Proxy does not forward /i/v1/ai/events (got 404); v1 SDKs send AI events there"],
        )

    @parameterized.expand(
        [
            (
                "ssl_error",
                requests.exceptions.SSLError("SSL certificate problem"),
                ["Failed to connect to proxy: invalid SSL certificate"],
            ),
            (
                "connection_error",
                requests.exceptions.ConnectionError("Connection refused"),
                ["Failed to connect to proxy"],
            ),
            # read_timeout guards the dedicated Timeout handler: ReadTimeout subclasses
            # requests.Timeout (not ConnectionError), so it must return the specific timeout
            # message rather than being caught by one of the later, more generic handlers.
            (
                "read_timeout",
                requests.exceptions.ReadTimeout("timed out"),
                ["Proxy did not respond within the timeout"],
            ),
            (
                "http_error",
                requests.exceptions.HTTPError(response=Mock(status_code=500)),
                ["Failed to send event to proxy, expected 200 but got 500"],
            ),
        ]
    )
    @pytest.mark.asyncio
    @patch("posthog.temporal.proxy_service.monitor.pinned_request")
    @patch("posthog.temporal.proxy_service.monitor.get_record")
    async def test_check_proxy_is_live_probe_errors(
        self, _name, post_side_effect, expected_errors, mock_get_record, mock_post
    ):
        mock_get_record.return_value = self.proxy_record
        mock_post.side_effect = post_side_effect

        result = await check_proxy_is_live(self.input)

        self.assertEqual(result.errors, expected_errors)

    @parameterized.expand(
        [
            ("url_authority_polyglot", "169.254.169.254:80/pad.example.com"),
            ("scheme_and_path", "https://example.com/x"),
            ("address_literal", "169.254.169.254"),
        ]
    )
    @pytest.mark.asyncio
    @patch("posthog.temporal.proxy_service.monitor.socket.create_connection")
    @patch("posthog.temporal.proxy_service.monitor.pinned_request")
    @patch("posthog.temporal.proxy_service.monitor.get_record")
    async def test_check_proxy_is_live_refuses_a_stored_domain_that_is_not_a_hostname(
        self, _name, domain, mock_get_record, mock_post, mock_create_connection
    ):
        self.proxy_record.domain = domain
        mock_get_record.return_value = self.proxy_record

        result = await check_proxy_is_live(self.input)

        self.assertEqual(result.errors, ["Proxy domain is not a plain hostname; recreate this proxy record"])
        mock_post.assert_not_called()
        mock_create_connection.assert_not_called()

    @pytest.mark.asyncio
    @time_machine.travel("2024-01-16 10:00:00", tick=False)
    @patch("posthog.temporal.proxy_service.monitor.validate_url_and_pin_ips")
    @patch("posthog.temporal.proxy_service.monitor.socket.create_connection")
    @patch("posthog.temporal.proxy_service.monitor.ssl.create_default_context")
    @patch("posthog.temporal.proxy_service.monitor.pinned_request")
    @patch("posthog.temporal.proxy_service.monitor.get_record")
    async def test_cert_check_connects_to_the_validated_address(
        self, mock_get_record, mock_post, mock_ssl_context, mock_create_connection, mock_validate
    ):
        mock_get_record.return_value = self.proxy_record
        mock_post.side_effect = _respond_by_path(Mock(status_code=200, raise_for_status=Mock(return_value=None)))
        mock_validate.return_value = PinnedUrlVerdict(
            allowed=True, reason=None, pinned_ips={ipaddress.ip_address("203.0.113.7")}
        )
        mock_create_connection.return_value = MagicMock()

        mock_socket = Mock()
        mock_socket.getpeercert.return_value = {"notAfter": "Feb  5 10:00:00 2024 GMT"}
        mock_wrapped_socket = Mock()
        mock_wrapped_socket.__enter__ = Mock(return_value=mock_socket)
        mock_wrapped_socket.__exit__ = Mock(return_value=None)
        mock_context = Mock()
        mock_context.wrap_socket.return_value = mock_wrapped_socket
        mock_ssl_context.return_value = mock_context

        result = await check_proxy_is_live(self.input)

        self.assertEqual(result.errors, [])
        # The socket carries no proxy settings, so the address it opens is the whole control. SNI
        # stays on the hostname so certificate verification still checks the configured name.
        mock_create_connection.assert_called_once_with(("203.0.113.7", 443), timeout=PROXY_LIVE_CHECK_TIMEOUT_S)
        self.assertEqual(mock_context.wrap_socket.call_args.kwargs["server_hostname"], self.proxy_record.domain)

    @pytest.mark.asyncio
    @patch("requests.adapters.HTTPAdapter.send")
    @patch("posthog.security.url_validation.resolve_host_ips", return_value={ipaddress.ip_address("127.0.0.1")})
    @patch("posthog.temporal.proxy_service.monitor.socket.create_connection")
    @patch("posthog.temporal.proxy_service.monitor.get_record")
    async def test_check_proxy_is_live_refuses_a_domain_the_probe_cannot_validate(
        self, mock_get_record, mock_create_connection, _mock_resolve, mock_send
    ):
        # The patch sits on the requests transport, not on pinned_request, so the assertion also
        # catches a test event that a plain requests call sends before the host check.
        self.proxy_record.domain = "proxy.example.com"
        mock_get_record.return_value = self.proxy_record
        mock_send.return_value = requests.Response()
        mock_send.return_value.status_code = 200

        result = await check_proxy_is_live(self.input)

        self.assertEqual(result.errors, ["Proxy domain does not resolve to a public address"])
        self.assertEqual(result.warnings, [])
        mock_send.assert_not_called()
        mock_create_connection.assert_not_called()

    @pytest.mark.asyncio
    @patch("posthog.temporal.proxy_service.monitor.validate_url_and_pin_ips")
    @patch("posthog.temporal.proxy_service.monitor.socket.create_connection")
    @patch("posthog.temporal.proxy_service.monitor.pinned_request")
    @patch("posthog.temporal.proxy_service.monitor.get_record")
    async def test_cert_check_does_not_connect_to_a_private_address(
        self, mock_get_record, mock_post, mock_create_connection, mock_validate
    ):
        mock_get_record.return_value = self.proxy_record
        mock_post.side_effect = _respond_by_path(Mock(status_code=200, raise_for_status=Mock(return_value=None)))
        mock_validate.return_value = PinnedUrlVerdict(allowed=False, reason="private address", pinned_ips=set())

        result = await check_proxy_is_live(self.input)

        self.assertEqual(result.errors, ["Proxy domain does not resolve to a public address"])
        mock_create_connection.assert_not_called()
        self.assertEqual(result.warnings, [])

    @pytest.mark.asyncio
    @patch("posthog.temporal.proxy_service.monitor.pinned_request")
    @patch("posthog.temporal.proxy_service.monitor.get_record")
    async def test_check_proxy_is_live_reports_cloudflare_1014(self, mock_get_record, mock_post):
        # A 403 body with Cloudflare error 1014 must report a hostname authorization problem,
        # not a bare status code.
        mock_get_record.return_value = self.proxy_record
        mock_response = Mock(status_code=403, text="<h1>Error 1014</h1>")
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_response)
        mock_post.return_value = mock_response

        result = await check_proxy_is_live(self.input)

        self.assertEqual(len(result.errors), 1)
        self.assertIn("1014", result.errors[0])
        self.assertEqual(result.warnings, [])

    @pytest.mark.asyncio
    @patch("posthog.temporal.proxy_service.monitor.pinned_request")
    @patch("posthog.temporal.proxy_service.monitor.get_record")
    async def test_check_proxy_is_live_rejects_redirect(self, mock_get_record, mock_post):
        # With allow_redirects=False a 3xx is not followed; raise_for_status only rejects 4xx/5xx,
        # so this guards that a redirect fails the check instead of silently marking the proxy live.
        mock_get_record.return_value = self.proxy_record
        mock_response = Mock(status_code=302)
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = await check_proxy_is_live(self.input)

        self.assertEqual(result.errors, ["Proxy returned a redirect (302); expected a direct 2xx response"])
        self.assertEqual(result.warnings, [])

    @pytest.mark.asyncio
    @time_machine.travel(
        "2024-01-16 10:00:00", tick=False
    )  # Frozen at Jan 16, cert expires Jan 25 (9 days later, < 14 day threshold)
    @patch("posthog.temporal.proxy_service.monitor.socket.create_connection")
    @patch("posthog.temporal.proxy_service.monitor.ssl.create_default_context")
    @patch("posthog.temporal.proxy_service.monitor.pinned_request")
    @patch("posthog.temporal.proxy_service.monitor.get_record")
    async def test_check_proxy_is_live_cert_expiring_soon(
        self, mock_get_record, mock_post, mock_ssl_context, mock_create_connection
    ):
        """Test certificate expiring soon warning"""
        mock_get_record.return_value = self.proxy_record

        # Mock successful HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_post.side_effect = _respond_by_path(mock_response)

        # Mock the raw socket the cert fetch opens so no real network connection is made
        mock_create_connection.return_value = MagicMock()

        # Mock SSL certificate that expires in 9 days (less than 14 day threshold)
        mock_cert = {"notAfter": "Jan 25 10:00:00 2024 GMT"}
        mock_socket = Mock()
        mock_socket.getpeercert.return_value = mock_cert

        mock_context = Mock()
        mock_wrapped_socket = Mock()
        mock_wrapped_socket.__enter__ = Mock(return_value=mock_socket)
        mock_wrapped_socket.__exit__ = Mock(return_value=None)
        mock_context.wrap_socket.return_value = mock_wrapped_socket
        mock_ssl_context.return_value = mock_context

        result = await check_proxy_is_live(self.input)

        self.assertEqual(result.errors, ["Live proxy certificate is expiring soon"])
        self.assertEqual(result.warnings, [])


def _hostname(status: CustomHostnameStatus, ssl_status=CustomHostnameSSLStatus.ACTIVE) -> CustomHostname:
    return CustomHostname(
        id="id",
        hostname="e.example.com",
        status=status,
        ssl=CustomHostnameSSL(status=ssl_status, validation_errors=[]),
    )


class TestCheckCloudflareCertificateStatus(SimpleTestCase):
    @parameterized.expand(
        [
            ("blocked", CustomHostnameStatus.BLOCKED),
            ("pending_blocked", CustomHostnameStatus.PENDING_BLOCKED),
            ("moved", CustomHostnameStatus.MOVED),
            ("pending_migration", CustomHostnameStatus.PENDING_MIGRATION),
        ]
    )
    @pytest.mark.asyncio
    @patch("posthog.temporal.proxy_service.monitor.get_custom_hostname_by_domain")
    async def test_blocked_hostname_is_error_even_when_cert_active(self, _name, status, mock_get):
        # An active SSL certificate must not mask a hostname that the edge blocked or moved.
        mock_get.return_value = _hostname(status=status, ssl_status=CustomHostnameSSLStatus.ACTIVE)

        result = await _check_cloudflare_certificate_status(Mock(domain="e.example.com"), Mock())

        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.warnings, [])

    @pytest.mark.asyncio
    @patch("posthog.temporal.proxy_service.monitor.get_custom_hostname_by_domain")
    async def test_active_hostname_and_cert_passes(self, mock_get):
        mock_get.return_value = _hostname(status=CustomHostnameStatus.ACTIVE)

        result = await _check_cloudflare_certificate_status(Mock(domain="e.example.com"), Mock())

        self.assertEqual(result.errors, [])
        self.assertEqual(result.warnings, [])
