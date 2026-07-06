import io
import time
from typing import cast

from django.http import HttpRequest
from django.test import TestCase, override_settings

from parameterized import parameterized
from rest_framework.parsers import JSONParser
from rest_framework.request import Request

from ee.api.agentic_provisioning.signature import (
    _parse_signature_header,
    compute_signature,
    verify_provisioning_signature,
)

HMAC_SECRET = "test_hmac_secret"


class TestParseSignatureHeader(TestCase):
    @parameterized.expand(
        [
            ("valid", f"t=1234567890,v1={'ab' * 32}", ("1234567890", "ab" * 32)),
            ("uppercase_hex", f"t=1234567890,v1={'AB' * 32}", ("1234567890", "AB" * 32)),
            ("missing_t", f"v1={'ab' * 32}", None),
            ("missing_v1", "t=1234567890", None),
            ("malformed_no_equals", "garbage", None),
            ("empty", "", None),
            ("short_hex", "t=1234567890,v1=abcd", None),
            ("non_numeric_timestamp", f"t=notanumber,v1={'ab' * 32}", None),
        ]
    )
    def test_parse(self, _name, header, expected):
        assert _parse_signature_header(header) == expected


@override_settings(STRIPE_SIGNING_SECRET=HMAC_SECRET)
class TestComputeSignature(TestCase):
    @parameterized.expand(
        [
            ("basic_body", 1700000000, b'{"hello":"world"}'),
            ("empty_body", 1700000000, b""),
            ("binary_body", 1700000000, b"\x00\x01\x02"),
        ]
    )
    def test_deterministic(self, _name, ts, body):
        sig1 = compute_signature(HMAC_SECRET, ts, body)
        sig2 = compute_signature(HMAC_SECRET, ts, body)
        assert sig1 == sig2
        assert len(sig1) == 64

    def test_different_secret_different_sig(self):
        body = b"test"
        sig1 = compute_signature("secret1", 1700000000, body)
        sig2 = compute_signature("secret2", 1700000000, body)
        assert sig1 != sig2

    def test_different_timestamp_different_sig(self):
        body = b"test"
        sig1 = compute_signature(HMAC_SECRET, 1700000000, body)
        sig2 = compute_signature(HMAC_SECRET, 1700000001, body)
        assert sig1 != sig2

    def test_different_body_different_sig(self):
        sig1 = compute_signature(HMAC_SECRET, 1700000000, b"body1")
        sig2 = compute_signature(HMAC_SECRET, 1700000000, b"body2")
        assert sig1 != sig2


@override_settings(STRIPE_SIGNING_SECRET=HMAC_SECRET)
class TestVerifySignatureAfterDRFParsing(TestCase):
    def _make_drf_request_with_consumed_stream(self, body: bytes) -> Request:
        django_request = HttpRequest()
        django_request.method = "POST"
        django_request.content_type = "application/json"
        django_request.META = {
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": "application/json",
            "CONTENT_LENGTH": str(len(body)),
        }
        django_request._stream = io.BytesIO(body)
        django_request._read_started = False  # type: ignore[attr-defined]

        drf_request = Request(django_request, parsers=[JSONParser()])
        _ = drf_request.data

        return cast(Request, drf_request)

    def test_returns_400_when_stream_consumed(self):
        body = b'{"email":"test@example.com"}'
        ts = int(time.time())
        sig = compute_signature(HMAC_SECRET, ts, body)

        drf_request = self._make_drf_request_with_consumed_stream(body)
        drf_request.META["HTTP_STRIPE_SIGNATURE"] = f"t={ts},v1={sig}"

        result = verify_provisioning_signature(drf_request)
        assert result is not None, "Body was consumed so signature can't be verified"
        assert result.status_code == 400
        assert result.data["error"]["code"] == "body_not_readable"

    def test_succeeds_when_stream_not_consumed(self):
        body = b'{"email":"test@example.com"}'
        ts = int(time.time())
        sig = compute_signature(HMAC_SECRET, ts, body)

        django_request = HttpRequest()
        django_request.method = "POST"
        django_request.content_type = "application/json"
        django_request.META = {
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": "application/json",
            "CONTENT_LENGTH": str(len(body)),
            "HTTP_STRIPE_SIGNATURE": f"t={ts},v1={sig}",
        }
        django_request._stream = io.BytesIO(body)
        django_request._read_started = False  # type: ignore[attr-defined]

        drf_request = Request(django_request, parsers=[JSONParser()])
        result = verify_provisioning_signature(drf_request)
        assert result is None

    def test_succeeds_when_body_cached_despite_stream_consumed(self):
        body = b'{"email":"test@example.com"}'
        ts = int(time.time())
        sig = compute_signature(HMAC_SECRET, ts, body)

        django_request = HttpRequest()
        django_request.method = "POST"
        django_request.content_type = "application/json"
        django_request.META = {
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": "application/json",
            "CONTENT_LENGTH": str(len(body)),
            "HTTP_STRIPE_SIGNATURE": f"t={ts},v1={sig}",
        }
        django_request._body = body
        django_request._stream = io.BytesIO(b"")
        django_request._read_started = True  # type: ignore[attr-defined]

        drf_request = Request(django_request, parsers=[JSONParser()])
        result = verify_provisioning_signature(drf_request)
        assert result is None

    def _make_request(self, body: bytes, sig_header: str) -> Request:
        django_request = HttpRequest()
        django_request.method = "POST"
        django_request.content_type = "application/json"
        django_request.META = {
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": "application/json",
            "CONTENT_LENGTH": str(len(body)),
            "HTTP_STRIPE_SIGNATURE": sig_header,
        }
        django_request._stream = io.BytesIO(body)
        django_request._read_started = False  # type: ignore[attr-defined]
        return cast(Request, Request(django_request, parsers=[JSONParser()]))

    def test_succeeds_with_multiple_signatures_during_rotation(self):
        # Stripe dual-signs while a signing-secret rotation is in flight, so the header
        # carries the stale (old secret) signature alongside the current one. The current
        # signature appears second here to guard against only checking the first v1.
        body = b'{"email":"test@example.com"}'
        ts = int(time.time())
        stale_sig = compute_signature("rotated_out_secret", ts, body)
        current_sig = compute_signature(HMAC_SECRET, ts, body)

        drf_request = self._make_request(body, f"t={ts},v1={stale_sig},v1={current_sig}")
        result = verify_provisioning_signature(drf_request)
        assert result is None

    @parameterized.expand(
        [
            (
                "no_signature_matches",
                lambda body, ts: (
                    f"t={ts},v1={compute_signature('wrong_a', ts, body)},v1={compute_signature('wrong_b', ts, body)}"
                ),
            ),
            ("stale_timestamp", lambda body, ts: f"t={ts - 301},v1={compute_signature(HMAC_SECRET, ts - 301, body)}"),
            ("wrong_scheme_only", lambda body, ts: f"t={ts},v0={compute_signature(HMAC_SECRET, ts, body)}"),
            ("missing_header", lambda body, ts: ""),
        ]
    )
    def test_rejects_invalid_signature(self, _name, build_header):
        body = b'{"email":"test@example.com"}'
        ts = int(time.time())

        drf_request = self._make_request(body, build_header(body, ts))
        result = verify_provisioning_signature(drf_request)
        assert result is not None
        assert result.status_code == 401
        assert result.data["error"]["code"] == "invalid_signature"

    def test_non_utf8_body_is_a_bad_request_not_a_signature_failure(self):
        body = b"\xff\xfe not valid utf-8"
        ts = int(time.time())

        drf_request = self._make_request(body, f"t={ts},v1={'ab' * 32}")
        result = verify_provisioning_signature(drf_request)
        assert result is not None
        assert result.status_code == 400
        assert result.data["error"]["code"] == "body_not_decodable"
