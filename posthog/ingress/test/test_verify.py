import re
import hmac
import time
import base64
from types import SimpleNamespace

from unittest.mock import patch

from django.test import SimpleTestCase

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from parameterized import parameterized

from posthog.ingress.verify.errors import VerifierUnavailable
from posthog.ingress.verify.jwt import _JWKS_CLIENTS, SIGNING_KEY_FACT, BearerJwt, _jwks_client
from posthog.ingress.verify.schemes import HmacSha256, HmacSignature, SnsSignature, Verification, VerificationOutcome

SECRET = "s3cret"
BODY = b'{"action":"opened"}'


def _digest(body: bytes = BODY, secret: str = SECRET, digest: str = "sha256") -> bytes:
    return hmac.digest(secret.encode(), body, digest)


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

        verification = scheme.verify(body=BODY, headers={"X-Signature": prefix + encoded})
        self.assertEqual(verification.outcome, VerificationOutcome.VERIFIED)
        # An HMAC over the raw body proves the sender holds the secret and nothing else, so it
        # hands `deliveries` nothing to cross-check the body against.
        self.assertEqual(verification.facts, {})
        self.assertEqual(
            scheme.verify(body=BODY, headers={"X-Signature": encoded}).outcome,
            VerificationOutcome.VERIFIED if prefix == "" else VerificationOutcome.INVALID,
        )

    def test_header_lookup_is_case_insensitive(self) -> None:
        scheme = HmacSha256(secret_getter=lambda: SECRET, signature_header="X-Hub-Signature-256", prefix="sha256=")
        self.assertEqual(
            scheme.verify(body=BODY, headers={"x-hub-signature-256": "sha256=" + _digest().hex()}).outcome,
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
        self.assertEqual(scheme.verify(body=BODY, headers=headers).outcome, expected)

    @parameterized.expand(
        [
            ("missing_header", {}, True),
            ("empty_header", {"X-Signature": ""}, True),
            ("malformed_header", {"X-Signature": "not-a-digest"}, True),
            ("missing_timestamp", {"X-Signature": "0" * 64}, True),
            ("malformed_timestamp", {"X-Signature": "0" * 64, "X-Timestamp": "yesterday"}, True),
            ("stale_timestamp", {"X-Signature": "0" * 64, "X-Timestamp": "1700000000"}, True),
            ("well_formed", {"X-Signature": "0" * 64, "X-Timestamp": "now"}, False),
            ("missing_header_but_no_secret", {}, False),
        ]
    )
    def test_headers_alone_decide_whether_the_body_is_worth_reading(
        self, _name: str, headers: dict[str, str], expected: bool
    ) -> None:
        # An unconfigured endpoint keeps its NOT_CONFIGURED answer, so the operator signal survives.
        secret = "" if _name == "missing_header_but_no_secret" else SECRET
        headers = {k: str(int(time.time())) if v == "now" else v for k, v in headers.items()}
        scheme = HmacSha256(
            secret_getter=lambda: secret,
            signature_header="X-Signature",
            signature_pattern=re.compile(r"^[0-9a-f]{64}$"),
            signed_input="v0_timestamp_body",
            timestamp_header="X-Timestamp",
        )
        self.assertEqual(scheme.rejects_headers(headers), expected)
        # Every refusal here is the same verdict the full check would reach on those headers.
        if expected:
            self.assertEqual(
                scheme.verify(body=BODY, headers=headers).outcome,
                VerificationOutcome.INVALID,
            )

    def test_missing_secret_is_not_configured_rather_than_invalid(self) -> None:
        scheme = HmacSha256(secret_getter=lambda: None, signature_header="X-Signature")
        self.assertEqual(
            scheme.verify(body=BODY, headers={"X-Signature": _digest().hex()}).outcome,
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

        self.assertEqual(scheme.verify(body=BODY, headers=headers).outcome, VerificationOutcome.VERIFIED)
        # The same signature over the body alone must not pass, or the replay window is decorative.
        self.assertEqual(
            scheme.verify(body=BODY, headers={**headers, "X-Slack-Signature": "v0=" + _digest().hex()}).outcome,
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

        self.assertEqual(scheme.verify(body=BODY, headers=headers).outcome, VerificationOutcome.INVALID)

    def test_signature_pattern_rejects_before_the_digest_runs(self) -> None:
        scheme = HmacSha256(
            secret_getter=lambda: SECRET,
            signature_header="X-Vapi-Signature",
            signature_pattern=re.compile(r"^[0-9a-f]{64}$"),
        )
        with patch("hmac.digest") as digest:
            self.assertEqual(
                scheme.verify(body=BODY, headers={"X-Vapi-Signature": "NOT-A-HEX-DIGEST"}).outcome,
                VerificationOutcome.INVALID,
            )
        digest.assert_not_called()

    def test_compares_in_constant_time(self) -> None:
        scheme = HmacSha256(secret_getter=lambda: SECRET, signature_header="X-Signature")
        with patch("hmac.compare_digest", wraps=hmac.compare_digest) as compare:
            scheme.verify(body=BODY, headers={"X-Signature": _digest().hex()})
        compare.assert_called_once()

    @parameterized.expand([("sha256", "sha256", "sha1"), ("sha1", "sha1", "sha256")])
    def test_the_declared_digest_is_the_one_that_verifies(self, _name: str, declared: str, other: str) -> None:
        scheme = HmacSignature(
            secret_getter=lambda: SECRET,
            signature_header="X-Signature",
            digest=declared,  # type: ignore[arg-type]
        )

        self.assertEqual(
            scheme.verify(body=BODY, headers={"X-Signature": _digest(digest=declared).hex()}).outcome,
            VerificationOutcome.VERIFIED,
        )
        self.assertEqual(
            scheme.verify(body=BODY, headers={"X-Signature": _digest(digest=other).hex()}).outcome,
            VerificationOutcome.INVALID,
        )

    def test_the_sha256_name_cannot_be_handed_another_digest(self) -> None:
        named = HmacSha256(secret_getter=lambda: SECRET, signature_header="X-Signature")
        explicit = HmacSignature(secret_getter=lambda: SECRET, signature_header="X-Signature", digest="sha256")

        self.assertEqual(named.digest, explicit.digest)
        # A name that promises SHA-256 and hashes something else is the trap this closes.
        with self.assertRaises(TypeError):
            HmacSha256(secret_getter=lambda: SECRET, signature_header="X-Signature", digest="sha1")

    @parameterized.expand(
        [
            ("missing_header", {}, True),
            ("empty_header", {"X-Signature": ""}, True),
            ("malformed_header", {"X-Signature": "not-a-digest"}, True),
            ("well_formed", {"X-Signature": "0" * 40}, False),
        ]
    )
    def test_headers_alone_decide_the_same_way_for_every_digest(
        self, _name: str, headers: dict[str, str], expected: bool
    ) -> None:
        # A header gate that read the digest would let an unsigned probe make a SHA-1 endpoint
        # read a body of up to the request limit, which the SHA-256 one refuses.
        pattern = re.compile(r"^[0-9a-f]{40}$")
        for digest in ("sha256", "sha1"):
            with self.subTest(digest=digest):
                scheme = HmacSignature(
                    secret_getter=lambda: SECRET,
                    signature_header="X-Signature",
                    signature_pattern=pattern,
                    digest=digest,
                )
                self.assertEqual(scheme.rejects_headers(headers), expected)


class TestSnsSignature(SimpleTestCase):
    def setUp(self) -> None:
        self.allowed = frozenset({"arn:aws:sns:eu-west-1:1:ses-events"})

    def _scheme(self, *, allowed: frozenset[str] | None = None) -> SnsSignature:
        return SnsSignature(allowed_topic_arns=lambda: self.allowed if allowed is None else allowed)

    def _verify(self, scheme: SnsSignature, *, body: bytes, verified: bool = True) -> VerificationOutcome:
        with patch("posthog.ingress.verify.schemes.verify_sns_message", return_value=verified):
            return scheme.verify(body=body, headers={}).outcome

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
        self.assertEqual(self._verify(self._scheme(), body=body, verified=verified), VerificationOutcome(expected))

    def test_empty_allowlist_is_not_configured(self) -> None:
        body = b'{"TopicArn": "arn:aws:sns:eu-west-1:1:ses-events"}'
        self.assertEqual(
            self._verify(self._scheme(allowed=frozenset()), body=body),
            VerificationOutcome.NOT_CONFIGURED,
        )

    def test_unparseable_body_is_invalid_rather_than_raising(self) -> None:
        self.assertEqual(self._verify(self._scheme(), body=b"not json"), VerificationOutcome.INVALID)

    def test_a_verifier_that_could_not_fetch_the_certificate_is_unavailable(self) -> None:
        body = b'{"TopicArn": "arn:aws:sns:eu-west-1:1:ses-events", "MessageId": "m1"}'

        with patch(
            "posthog.ingress.verify.schemes.verify_sns_message", side_effect=VerifierUnavailable("no certificate")
        ):
            outcome = self._scheme().verify(body=body, headers={}).outcome

        self.assertEqual(outcome, VerificationOutcome.UNAVAILABLE)


JWKS_URI = "https://login.example.com/v1/.well-known/keys"
AUDIENCE = "00000000-0000-0000-0000-000000000001"
ISSUER = "https://api.issuer.example.com"
SERVICE_URL = "https://connector.example.com/emea/"
KEY_ID = "signing-key-1"


class TestBearerJwt(SimpleTestCase):
    private_key: rsa.RSAPrivateKey

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self) -> None:
        # The client map is module-global, so a test must not inherit another test's clients.
        _JWKS_CLIENTS.clear()
        self.addCleanup(_JWKS_CLIENTS.clear)

    def _token(self, *, expires_in_seconds: int | None = 300, **claims: str) -> str:
        payload: dict[str, object] = {"iss": ISSUER, "aud": AUDIENCE, "serviceurl": SERVICE_URL, **claims}
        if expires_in_seconds is not None:
            payload["exp"] = int(time.time()) + expires_in_seconds
        return jwt.encode(payload, self.private_key, algorithm="RS256", headers={"kid": KEY_ID})

    def _scheme(
        self,
        *,
        jwks_uri: str | None = JWKS_URI,
        audience: str | None = AUDIENCE,
        issuers: frozenset[str] = frozenset({ISSUER}),
    ) -> BearerJwt:
        return BearerJwt(
            jwks_uri_getter=lambda: jwks_uri,
            audience_getter=lambda: audience,
            issuers_getter=lambda: issuers,
        )

    def _verify(self, scheme: BearerJwt, headers: dict[str, str]) -> Verification:
        # The JWKS fetch is the only boundary mocked here; the decode below it is the real one.
        signing_key = SimpleNamespace(key=self.private_key.public_key())
        with patch.object(jwt.PyJWKClient, "get_signing_key_from_jwt", return_value=signing_key):
            return scheme.verify(body=BODY, headers=headers)

    def test_verified_token_hands_its_claims_to_deliveries(self) -> None:
        verification = self._verify(self._scheme(), {"Authorization": "Bearer " + self._token()})

        self.assertEqual(verification.outcome, VerificationOutcome.VERIFIED)
        self.assertEqual(verification.facts["iss"], ISSUER)
        self.assertEqual(verification.facts["aud"], AUDIENCE)
        self.assertEqual(verification.facts["serviceurl"], SERVICE_URL)

    @parameterized.expand(
        [
            ("missing_header", None),
            ("another_auth_scheme", "Basic {token}"),
            ("token_without_the_bearer_prefix", "{token}"),
        ]
    )
    def test_rejects_a_request_that_carries_no_bearer_token(self, _name: str, template: str | None) -> None:
        headers = {} if template is None else {"Authorization": template.format(token=self._token())}

        self.assertEqual(self._verify(self._scheme(), headers).outcome, VerificationOutcome.INVALID)
        # The same verdict from the headers alone, so the body is never read for it.
        self.assertTrue(self._scheme().rejects_headers(headers))

    @parameterized.expand(
        [
            ("foreign_issuer", {"iss": "https://issuer.example.org"}, 300),
            ("audience_of_another_app", {"aud": "00000000-0000-0000-0000-000000000002"}, 300),
            ("expired_beyond_the_leeway", {}, -3600),
            ("no_expiry_claim", {}, None),
        ]
    )
    def test_rejects_a_token_this_app_must_not_accept(
        self, _name: str, claims: dict[str, str], expires_in_seconds: int | None
    ) -> None:
        token = self._token(expires_in_seconds=expires_in_seconds, **claims)

        headers = {"Authorization": "Bearer " + token}
        self.assertEqual(self._verify(self._scheme(), headers).outcome, VerificationOutcome.INVALID)

    def test_the_key_that_signed_the_token_reaches_deliveries_with_what_the_jwks_published(self) -> None:
        # A real PyJWKClient over a real JWKS document, so a PyJWT release that stops carrying the
        # members an incarnation reads fails here rather than at a webhook endpoint.
        published = {
            **RSAAlgorithm.to_jwk(self.private_key.public_key(), as_dict=True),
            "kid": KEY_ID,
            "endorsements": ["msteams"],
        }
        headers = {"Authorization": "Bearer " + self._token()}

        with patch.object(jwt.PyJWKClient, "fetch_data", return_value={"keys": [published]}):
            verification = self._scheme().verify(body=BODY, headers=headers)

        self.assertEqual(verification.outcome, VerificationOutcome.VERIFIED)
        self.assertEqual(verification.facts[SIGNING_KEY_FACT]["endorsements"], ["msteams"])
        self.assertEqual(verification.facts[SIGNING_KEY_FACT]["kid"], KEY_ID)

    def test_rejects_a_tampered_signature(self) -> None:
        header, payload, signature = self._token().split(".")
        # The first character, not the last: base64 drops the last one's padding bits, so
        # flipping it can leave the signature bytes unchanged.
        flipped = ("A" if signature[0] != "A" else "B") + signature[1:]

        headers = {"Authorization": f"Bearer {header}.{payload}.{flipped}"}
        self.assertEqual(self._verify(self._scheme(), headers).outcome, VerificationOutcome.INVALID)

    @parameterized.expand(
        [
            (
                "key_id_the_jwks_does_not_serve",
                jwt.PyJWKClientError("unable to find a key"),
                VerificationOutcome.INVALID,
            ),
            (
                "jwks_that_could_not_be_fetched",
                jwt.PyJWKClientConnectionError("connection error"),
                VerificationOutcome.UNAVAILABLE,
            ),
        ]
    )
    def test_a_signing_key_failure_separates_the_token_from_the_fetch(
        self, _name: str, error: Exception, expected: VerificationOutcome
    ) -> None:
        headers = {"Authorization": "Bearer " + self._token()}

        with patch.object(jwt.PyJWKClient, "get_signing_key_from_jwt", side_effect=error):
            outcome = self._scheme().verify(body=BODY, headers=headers).outcome
        self.assertEqual(outcome, expected)

    @parameterized.expand(
        [
            ("no_audience", JWKS_URI, None, frozenset({ISSUER})),
            ("no_issuers", JWKS_URI, AUDIENCE, frozenset()),
        ]
    )
    def test_missing_configuration_is_not_configured_rather_than_invalid(
        self, _name: str, jwks_uri: str | None, audience: str | None, issuers: frozenset[str]
    ) -> None:
        scheme = self._scheme(jwks_uri=jwks_uri, audience=audience, issuers=issuers)

        headers = {"Authorization": "Bearer " + self._token()}
        self.assertEqual(self._verify(scheme, headers).outcome, VerificationOutcome.NOT_CONFIGURED)

    def test_a_signing_key_uri_the_getter_could_not_discover_is_unavailable(self) -> None:
        # The getter fetches the URI from the issuer's metadata document and answers None when
        # that fetch fails. Reading it as unconfigured gives a provider whose unconfigured status
        # is a 4xx, which the issuer does not retry, and the outage then loses every delivery.
        scheme = self._scheme(jwks_uri=None, audience=AUDIENCE, issuers=frozenset({ISSUER}))

        headers = {"Authorization": "Bearer " + self._token()}
        self.assertEqual(self._verify(scheme, headers).outcome, VerificationOutcome.UNAVAILABLE)

    def test_an_unconfigured_instance_buys_no_signing_key_discovery(self) -> None:
        # The getter reaches the issuer over the network, and this endpoint is public.
        calls = 0

        def jwks_uri_getter() -> str:
            nonlocal calls
            calls += 1
            return JWKS_URI

        scheme = BearerJwt(
            jwks_uri_getter=jwks_uri_getter,
            audience_getter=lambda: None,
            issuers_getter=lambda: frozenset({ISSUER}),
        )

        self._verify(scheme, {"Authorization": "Bearer " + self._token()})
        self.assertEqual(calls, 0)

    def test_reuses_one_jwks_client_per_uri(self) -> None:
        # The client holds the key cache, so a client per delivery is a JWKS fetch per delivery.
        self.assertIs(_jwks_client(JWKS_URI), _jwks_client(JWKS_URI))
        self.assertIsNot(_jwks_client(JWKS_URI), _jwks_client("https://login.example.org/keys"))
