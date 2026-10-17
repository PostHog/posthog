import ssl
import hmac
import json
import base64
import asyncio
import hashlib
from functools import partial
from ipaddress import ip_address

from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

import httpx
import httpcore
from parameterized import parameterized
from pydantic import JsonValue
from rest_framework.exceptions import ValidationError

from posthog.security.pinned_httpx import pinned_client
from posthog.security.url_validation import PinnedUrlVerdict

from products.cdp.backend.mcp_event_delivery import MCPCallbackError, signed_headers, signing_key, verify_callback
from products.cdp.backend.mcp_event_envelope import MCPEventEnvelopeSerializer


class TestMCPEventSigning(SimpleTestCase):
    @parameterized.expand(["invalid", "whsec_!", "whsec_YQ==", "whsec_" + base64.b64encode(b"a" * 65).decode()])
    def test_rejects_invalid_signing_secrets(self, secret: str) -> None:
        with self.assertRaises(ValidationError):
            signing_key(secret)

    def setUp(self) -> None:
        super().setUp()
        self.enterContext(
            patch(
                "products.cdp.backend.mcp_event_delivery.validate_url_and_pin_ips",
                return_value=PinnedUrlVerdict(allowed=True, reason=None, pinned_ips={ip_address("93.184.216.34")}),
            )
        )
        self.enterContext(
            patch(
                "products.cdp.backend.mcp_event_delivery.pinned_client",
                side_effect=partial(pinned_client, trust_env=False),
            )
        )
        self.secret = "whsec_" + base64.b64encode(b"a" * 32).decode()

    @parameterized.expand([(200, "echo"), (200, "wrong"), (302, "echo"), (500, "echo"), (200, "oversized")])
    def test_callback_must_echo_the_signed_challenge(self, status: int, mode: str) -> None:
        async def respond(request: httpx.Request) -> httpx.Response:
            message = (
                request.headers["webhook-id"].encode()
                + b"."
                + request.headers["webhook-timestamp"].encode()
                + b"."
                + request.content
            )
            signature = base64.b64encode(hmac.new(b"a" * 32, message, hashlib.sha256).digest()).decode()
            self.assertEqual(request.headers["webhook-signature"], "v1," + signature)
            self.assertEqual(request.headers["X-MCP-Subscription-Id"], "test-subscription")
            challenge = json.loads(request.content)["challenge"]
            payload = {"challenge": challenge if mode == "echo" else "wrong"}
            raw = b"x" * 9000 if mode == "oversized" else json.dumps(payload).encode()
            return httpx.Response(status, stream=httpx.ByteStream(raw))

        with patch("httpx.AsyncHTTPTransport.handle_async_request", side_effect=respond):
            if status == 200 and mode == "echo":
                verify_callback(
                    subscription_id="test-subscription", url="https://example.com/callback", secret=self.secret
                )
            else:
                with self.assertRaises(MCPCallbackError):
                    verify_callback(
                        subscription_id="test-subscription", url="https://example.com/callback", secret=self.secret
                    )

    @parameterized.expand(
        [
            "http://example.com/callback",
            "https://example:password@example.com/callback",
            "https://@example.com/callback",
            "https://example.com/callback#fragment",
            "https://[example/callback",
        ]
    )
    def test_invalid_callback_url_is_rejected_before_network_access(self, url: str) -> None:
        with (
            patch("products.cdp.backend.mcp_event_delivery.validate_url_and_pin_ips") as validate,
            self.assertRaises(ValidationError) as caught,
        ):
            verify_callback(subscription_id="example-subscription", url=url, secret=self.secret)
        validate.assert_not_called()
        self.assertNotIn(url, str(caught.exception))

    def test_standard_webhooks_signature_preserves_utf8_body(self) -> None:
        headers = signed_headers(
            subscription_id="example-subscription",
            webhook_id="example-event",
            body='{"message":"héllo"}',
            secret=self.secret,
            signed_at=1700000000,
        )
        self.assertEqual(headers["webhook-id"], "example-event")
        self.assertEqual(headers["webhook-timestamp"], "1700000000")
        self.assertEqual(headers["webhook-signature"], "v1,5Mi8Lo9fF/q6194GNsKBNCmHwcnxHy43GoS3EWee/8Y=")
        self.assertEqual(headers["X-MCP-Subscription-Id"], "example-subscription")

    def test_callback_deadline_cancels_a_trickling_response_header(self) -> None:
        clock = [0.0]
        reads = 0
        stream = httpcore.AsyncMockStream([])

        async def read(max_bytes: int, timeout: float | None = None) -> bytes:
            nonlocal reads
            reads += 1
            clock[0] += 1
            await asyncio.sleep(0)
            return b"HTTP/1.1 200 OK\r\nX-Slow: " if reads == 1 else b"x"

        with (
            patch("asyncio.BaseEventLoop.time", side_effect=lambda: clock[0]),
            patch("httpcore.AnyIOBackend.connect_tcp", return_value=stream),
            patch.object(stream, "read", side_effect=read),
            patch.object(stream, "aclose", wraps=stream.aclose) as close,
            self.assertRaises(MCPCallbackError) as caught,
        ):
            verify_callback(subscription_id="test-subscription", url="https://example.com/callback", secret=self.secret)
        self.assertEqual(caught.exception.reason, "timeout")
        close.assert_awaited()

    @parameterized.expand(["timeout", "tls_error", "connection_failed", "invalid_url"])
    def test_callback_transport_errors_remain_sanitized(self, reason: str) -> None:
        async def respond(request: httpx.Request) -> httpx.Response:
            if reason == "timeout":
                raise httpx.ReadTimeout("example timeout")
            if reason == "tls_error":
                raise httpx.ConnectError("example TLS failure") from ssl.SSLError("example certificate failure")
            raise httpx.ConnectError("example connection failure")

        with (
            patch("httpx.AsyncHTTPTransport.handle_async_request", side_effect=respond),
            self.assertRaises(MCPCallbackError) as caught,
        ):
            url = "https://example.com:abc/callback" if reason == "invalid_url" else "https://example.com/callback"
            verify_callback(subscription_id="test-subscription", url=url, secret=self.secret)
        self.assertEqual(caught.exception.reason, "connection_failed" if reason == "invalid_url" else reason)
        self.assertNotIn("example", str(caught.exception))


class TestMCPEventEnvelope(SimpleTestCase):
    @parameterized.expand(
        [
            ("event_id", {"eventId": 123}),
            ("event_name", {"name": "other.event"}),
            ("cursor", {"cursor": "replay"}),
            ("timestamp", {"timestamp": "2026-01-01T00:00:00"}),
            ("properties", {"data": {"event": "example_event", "distinct_id": "sample-user", "properties": []}}),
            ("data_type", {"data": {"event": 123, "distinct_id": "sample-user", "properties": {}}}),
            ("extra", {"extra": True}),
        ]
    )
    def test_rejects_invalid_envelopes(self, _name: str, overrides: dict[str, JsonValue]) -> None:
        envelope: dict[str, JsonValue] = {
            "eventId": "sample-event",
            "name": "posthog.event_captured",
            "timestamp": timezone.now().isoformat(),
            "data": {"event": "example_event", "distinct_id": "sample-user", "properties": {}},
            "cursor": None,
            **overrides,
        }
        with self.assertRaises(ValidationError):
            MCPEventEnvelopeSerializer.parse(json.dumps(envelope))

    def test_valid_envelope_round_trip_preserves_content(self) -> None:
        value: dict[str, JsonValue] = {
            "eventId": "example-event",
            "name": "posthog.event_captured",
            "timestamp": "2026-01-01T00:00:00Z",
            "data": {
                "event": "  example event  ",
                "distinct_id": "  example-user  ",
                "properties": {"nested": {"items": [None, True, 3, "héllo"]}},
            },
            "cursor": None,
        }
        envelope = MCPEventEnvelopeSerializer.parse(json.dumps(value))
        self.assertEqual(envelope.data.event, "  example event  ")
        self.assertEqual(envelope.data.distinct_id, "  example-user  ")
        self.assertEqual(json.loads(MCPEventEnvelopeSerializer.render(envelope)), value)
