import re
import hmac
import time
import base64

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.ingress.verify.schemes import HmacSha256, SnsSignature, VerificationOutcome

SECRET = "s3cret"
BODY = b'{"action":"opened"}'


def _digest(body: bytes = BODY, secret: str = SECRET) -> bytes:
    return hmac.digest(secret.encode(), body, "sha256")


class TestHmacSha256(SimpleTestCase):
    @parameterized.expand(
        [
            ("github_hex_prefix", "hex", "sha256="),
            ("bare_hex", "hex", ""),
            ("base64_prefix", "base64", "v0="),
        ]
    )
    def test_accepts_its_own_encoding_and_prefix(self, _name: str, encoding: str, prefix: str) -> None:
        digest = _digest()
        encoded = base64.b64encode(digest).decode() if encoding == "base64" else digest.hex()
        scheme = HmacSha256(
            secret_getter=lambda: SECRET,
            signature_header="X-Signature",
            prefix=prefix,
            encoding=encoding,  # type: ignore[arg-type]
        )

        self.assertEqual(
            scheme.verify(body=BODY, headers={"X-Signature": prefix + encoded}),
            VerificationOutcome.VERIFIED,
        )
        self.assertEqual(
            scheme.verify(body=BODY, headers={"X-Signature": encoded}),
            VerificationOutcome.VERIFIED if prefix == "" else VerificationOutcome.INVALID,
        )

    def test_header_lookup_is_case_insensitive(self) -> None:
        scheme = HmacSha256(secret_getter=lambda: SECRET, signature_header="X-Hub-Signature-256", prefix="sha256=")
        self.assertEqual(
            scheme.verify(body=BODY, headers={"x-hub-signature-256": "sha256=" + _digest().hex()}),
            VerificationOutcome.VERIFIED,
        )

    @parameterized.expand(
        [
            ("missing_header", {}, VerificationOutcome.INVALID),
            ("empty_header", {"X-Signature": ""}, VerificationOutcome.INVALID),
            ("wrong_digest", {"X-Signature": "sha256=" + "0" * 64}, VerificationOutcome.INVALID),
            ("non_ascii_header", {"X-Signature": "sha256=ÿ" + "0" * 63}, VerificationOutcome.INVALID),
        ]
    )
    def test_rejects_unsigned_and_wrongly_signed_bodies(
        self, _name: str, headers: dict[str, str], expected: VerificationOutcome
    ) -> None:
        scheme = HmacSha256(secret_getter=lambda: SECRET, signature_header="X-Signature", prefix="sha256=")
        self.assertEqual(scheme.verify(body=BODY, headers=headers), expected)

    def test_missing_secret_is_not_configured_rather_than_invalid(self) -> None:
        scheme = HmacSha256(secret_getter=lambda: None, signature_header="X-Signature")
        self.assertEqual(
            scheme.verify(body=BODY, headers={"X-Signature": _digest().hex()}),
            VerificationOutcome.NOT_CONFIGURED,
        )

    def test_v0_timestamp_input_signs_timestamp_with_body(self) -> None:
        timestamp = str(int(time.time()))
        scheme = HmacSha256(
            secret_getter=lambda: SECRET,
            signature_header="X-Slack-Signature",
            prefix="v0=",
            signed_input="v0_timestamp_body",
            timestamp_header="X-Slack-Request-Timestamp",
        )
        signed = b"v0:" + timestamp.encode() + b":" + BODY
        headers = {
            "X-Slack-Signature": "v0=" + _digest(signed).hex(),
            "X-Slack-Request-Timestamp": timestamp,
        }

        self.assertEqual(scheme.verify(body=BODY, headers=headers), VerificationOutcome.VERIFIED)
        # The same signature over the body alone must not pass, or the replay window is decorative.
        self.assertEqual(
            scheme.verify(body=BODY, headers={**headers, "X-Slack-Signature": "v0=" + _digest().hex()}),
            VerificationOutcome.INVALID,
        )

    @parameterized.expand(
        [
            ("too_old", -3600),
            ("too_far_ahead", 3600),
            ("unparseable", None),
        ]
    )
    def test_rejects_a_replayed_timestamp(self, _name: str, offset_seconds: int | None) -> None:
        timestamp = "not-a-time" if offset_seconds is None else str(int(time.time()) + offset_seconds)
        scheme = HmacSha256(
            secret_getter=lambda: SECRET,
            signature_header="X-Signature",
            signed_input="v0_timestamp_body",
            timestamp_header="X-Timestamp",
            timestamp_max_age_seconds=300,
            timestamp_max_future_seconds=60,
        )
        signed = b"v0:" + timestamp.encode() + b":" + BODY
        headers = {"X-Signature": _digest(signed).hex(), "X-Timestamp": timestamp}

        self.assertEqual(scheme.verify(body=BODY, headers=headers), VerificationOutcome.INVALID)

    def test_signature_pattern_rejects_before_the_digest_runs(self) -> None:
        scheme = HmacSha256(
            secret_getter=lambda: SECRET,
            signature_header="X-Vapi-Signature",
            signature_pattern=re.compile(r"^[0-9a-f]{64}$"),
        )
        with patch("hmac.digest") as digest:
            self.assertEqual(
                scheme.verify(body=BODY, headers={"X-Vapi-Signature": "NOT-A-HEX-DIGEST"}),
                VerificationOutcome.INVALID,
            )
        digest.assert_not_called()

    def test_compares_in_constant_time(self) -> None:
        scheme = HmacSha256(secret_getter=lambda: SECRET, signature_header="X-Signature")
        with patch("hmac.compare_digest", wraps=hmac.compare_digest) as compare:
            scheme.verify(body=BODY, headers={"X-Signature": _digest().hex()})
        compare.assert_called_once()


class TestSnsSignature(SimpleTestCase):
    def setUp(self) -> None:
        self.allowed = frozenset({"arn:aws:sns:eu-west-1:1:ses-events"})

    def _scheme(self, *, verified: bool = True, allowed: frozenset[str] | None = None) -> SnsSignature:
        return SnsSignature(
            verify_message=lambda message: verified,
            allowed_topic_arns=lambda: self.allowed if allowed is None else allowed,
        )

    @parameterized.expand(
        [
            ("allowed_topic_and_valid_signature", "arn:aws:sns:eu-west-1:1:ses-events", True, "verified"),
            ("foreign_topic", "arn:aws:sns:eu-west-1:2:someone-elses", True, "invalid"),
            ("allowed_topic_but_bad_signature", "arn:aws:sns:eu-west-1:1:ses-events", False, "invalid"),
        ]
    )
    def test_needs_both_the_allowlist_and_the_signature(
        self, _name: str, topic_arn: str, verified: bool, expected: str
    ) -> None:
        body = f'{{"TopicArn": "{topic_arn}", "MessageId": "m1"}}'.encode()
        self.assertEqual(self._scheme(verified=verified).verify(body=body, headers={}), VerificationOutcome(expected))

    def test_empty_allowlist_is_not_configured(self) -> None:
        body = b'{"TopicArn": "arn:aws:sns:eu-west-1:1:ses-events"}'
        self.assertEqual(
            self._scheme(allowed=frozenset()).verify(body=body, headers={}),
            VerificationOutcome.NOT_CONFIGURED,
        )

    def test_unparseable_body_is_invalid_rather_than_raising(self) -> None:
        self.assertEqual(self._scheme().verify(body=b"not json", headers={}), VerificationOutcome.INVALID)
