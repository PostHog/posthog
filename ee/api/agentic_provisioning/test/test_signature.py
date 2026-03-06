from django.test import TestCase, override_settings

from parameterized import parameterized

from ee.api.agentic_provisioning.signature import _parse_signature_header, compute_signature

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


@override_settings(STRIPE_APP_SECRET_KEY=HMAC_SECRET)
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
