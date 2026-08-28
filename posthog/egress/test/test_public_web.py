from contextlib import nullcontext

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized
from requests.structures import CaseInsensitiveDict

from posthog.egress.limiter.policies import Priority, resolve_policy
from posthog.egress.public_web.limiter import consume_public_web_sync
from posthog.egress.public_web.transport import PublicWebFetchError, public_web_get
from posthog.security.pinned_requests import SSRFBlockedError


def _streaming_response(*, headers: dict[str, str] | None = None, chunks: list[bytes] | None = None) -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.status_code = 200
    response.headers = CaseInsensitiveDict(headers or {})
    response.iter_content.return_value = chunks or [b"ok"]
    return response


class TestPublicWebTransport(SimpleTestCase):
    def test_request_is_pinned_bounded_and_charged_to_the_hostname(self) -> None:
        response = _streaming_response(chunks=[b"hello", b" world"])
        session = MagicMock(spec=requests.Session)
        session.request.return_value = response

        with (
            patch("posthog.egress.public_web.transport.pinned_session", return_value=nullcontext(session)) as pinned,
            patch("posthog.egress.public_web.transport.consume_public_web_sync", return_value=True) as consume,
            patch("posthog.egress.public_web.transport.record_public_web_response") as record_response,
        ):
            result = public_web_get("https://Example.com/robots.txt", source="test", endpoint="robots", max_bytes=32)

        pinned.assert_called_once_with("https://Example.com/robots.txt")
        consume.assert_called_once_with("example.com", priority=Priority.NORMAL, source="test")
        self.assertEqual(result["body"], b"hello world")
        self.assertFalse(session.request.call_args.kwargs["allow_redirects"])
        self.assertTrue(session.request.call_args.kwargs["stream"])
        self.assertEqual(
            session.request.call_args.kwargs["headers"]["User-Agent"],
            "PostHog-PublicWeb/1.0 (+https://posthog.com)",
        )
        record_response.assert_called_once_with(
            response,
            source="test",
            method="GET",
            endpoint="robots",
        )
        response.close.assert_called_once()

    def test_transport_uses_a_shared_public_web_user_agent(self) -> None:
        response = _streaming_response()
        session = MagicMock(spec=requests.Session)
        session.request.return_value = response

        with (
            patch("posthog.egress.public_web.transport.pinned_session", return_value=nullcontext(session)),
            patch("posthog.egress.public_web.transport.consume_public_web_sync", return_value=True),
            patch("posthog.egress.public_web.transport.record_public_web_response"),
        ):
            public_web_get("https://example.com", source="test", endpoint="homepage", max_bytes=32)

        self.assertEqual(
            session.request.call_args.kwargs["headers"]["User-Agent"],
            "PostHog-PublicWeb/1.0 (+https://posthog.com)",
        )

    def test_absolute_deadline_bounds_the_request_and_stream(self) -> None:
        response = _streaming_response(chunks=[b"ok"])
        session = MagicMock(spec=requests.Session)
        session.request.return_value = response

        with (
            patch("posthog.egress.public_web.transport.pinned_session", return_value=nullcontext(session)),
            patch("posthog.egress.public_web.transport.consume_public_web_sync", return_value=True),
            patch("posthog.egress.public_web.transport.record_public_web_response"),
            patch("posthog.egress.public_web.transport.time.monotonic", side_effect=[100.0, 101.0, 106.0]),
            self.assertRaises(PublicWebFetchError),
        ):
            public_web_get(
                "https://example.com",
                source="test",
                endpoint="homepage",
                max_bytes=32,
                max_duration_seconds=5.0,
            )

        self.assertEqual(session.request.call_args.kwargs["timeout"], (3.0, 4.0))
        response.close.assert_called_once()

    @parameterized.expand(
        [
            ("ssrf", SSRFBlockedError("blocked")),
            ("timeout", requests.Timeout("timed out")),
        ]
    )
    def test_unsafe_or_failed_connections_use_the_typed_error(self, _name: str, error: Exception) -> None:
        with (
            patch("posthog.egress.public_web.transport.pinned_session", side_effect=error),
            self.assertRaises(PublicWebFetchError),
        ):
            public_web_get("https://example.com", source="test", endpoint="homepage", max_bytes=32)

    @parameterized.expand(
        [
            ("declared", {"Content-Length": "33"}, [b"ok"]),
            ("streamed", {}, [b"a" * 16, b"b" * 17]),
        ]
    )
    def test_response_larger_than_the_caller_limit_is_rejected(
        self, _name: str, headers: dict[str, str], chunks: list[bytes]
    ) -> None:
        response = _streaming_response(headers=headers, chunks=chunks)

        with (
            patch(
                "posthog.egress.public_web.transport.pinned_session",
                return_value=nullcontext(MagicMock(spec=requests.Session)),
            ),
            patch("posthog.egress.public_web.transport.consume_public_web_sync", return_value=True),
            patch("posthog.egress.public_web.transport.record_public_web_response"),
            patch("posthog.egress.public_web.transport._public_web_client.request", return_value=response),
            self.assertRaises(PublicWebFetchError),
        ):
            public_web_get("https://example.com", source="test", endpoint="homepage", max_bytes=32)

        response.close.assert_called_once()

    @parameterized.expand(
        [
            ("credentials", "https://token@example.com"),
            ("unsupported_scheme", "ftp://example.com"),
            ("missing_host", "https:///path"),
            ("invalid_port", "https://example.com:not-a-port"),
        ]
    )
    def test_invalid_target_is_rejected_before_pinning(self, _name: str, url: str) -> None:
        with patch("posthog.egress.public_web.transport.pinned_session") as pinned:
            with self.assertRaises(PublicWebFetchError):
                public_web_get(url, source="test", endpoint="homepage", max_bytes=32)
        pinned.assert_not_called()

    @override_settings(PUBLIC_WEB_EGRESS_PER_MINUTE_BUDGET=7, PUBLIC_WEB_EGRESS_HOURLY_BUDGET=11)
    def test_hostname_policy_uses_public_web_settings(self) -> None:
        self.assertTrue(consume_public_web_sync("Example.com", source="test"))
        self.assertEqual(resolve_policy("public_web:host:example.com").limits, ((7, 60.0), (11, 3600.0)))
