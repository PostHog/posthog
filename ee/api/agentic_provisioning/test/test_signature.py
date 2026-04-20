import io
import time

from django.http import HttpRequest
from django.test import TestCase, override_settings

from parameterized import parameterized
from rest_framework.parsers import JSONParser
from rest_framework.request import Request

from ee.api.agentic_provisioning.signature import _parse_signature_header, compute_signature, verify_stripe_signature

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

        return drf_request

    def test_returns_400_when_stream_consumed(self):
        body = b'{"email":"test@example.com"}'
        ts = int(time.time())
        sig = compute_signature(HMAC_SECRET, ts, body)

        drf_request = self._make_drf_request_with_consumed_stream(body)
        drf_request.META["HTTP_STRIPE_SIGNATURE"] = f"t={ts},v1={sig}"

        result = verify_stripe_signature(drf_request)
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
        result = verify_stripe_signature(drf_request)
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
        result = verify_stripe_signature(drf_request)
        assert result is None
