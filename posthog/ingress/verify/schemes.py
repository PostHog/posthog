"""Signature schemes: the part of a provider incarnation that decides "this is really them".

A scheme with a network step answers `UNAVAILABLE` when that step fails on transport rather than
on the signature, because a fetch that never completed proves nothing about the caller. `BearerJwt`
does this for a JWKS fetch failure, and `SnsSignature` for a signing certificate its verifier
could not fetch.
"""

import re
import hmac
import json
import time
import base64
from collections.abc import Callable, Mapping
from dataclasses import field
from enum import StrEnum
from typing import Any, Literal, Protocol

import structlog

from posthog.dataclasses import frozen
from posthog.ingress.verify.errors import VerifierUnavailable
from posthog.ingress.verify.sns_signature import verify_sns_message

logger = structlog.get_logger(__name__)

SignedInput = Literal["body", "v0_timestamp_body"]
SignatureEncoding = Literal["hex", "base64"]
# SHA-1 is on this list because one provider signs with it, not because it is a choice worth
# making for a new one. Reach for `HmacSha256` unless the provider leaves no option.
HmacDigest = Literal["sha256", "sha1"]


class VerificationOutcome(StrEnum):
    VERIFIED = "verified"
    INVALID = "invalid"
    # The instance holds no secret for this provider app, which is an operator problem
    # rather than a caller one, so incarnations answer it with their own status code.
    NOT_CONFIGURED = "not_configured"
    # Verification could not run right now, so the sender is asked to retry.
    UNAVAILABLE = "unavailable"


@frozen
class Verification:
    """What a signature check concluded, and what it proved on the way.

    A scheme that checks a signed token learns more than "this is really them": the claims it
    validated name the sender and the audience. `facts` carries those to `deliveries`, so an
    incarnation can cross-check the body against what was actually signed, rather than trusting
    a field of the body that says the same thing. A fact is not always a claim: `BearerJwt` also
    puts the key that signed the token there, because a JWKS can say what one key is allowed to
    sign and the token cannot. An HMAC over raw bytes proves nothing beyond the signature and
    leaves `facts` empty.
    """

    outcome: VerificationOutcome
    facts: Mapping[str, Any] = field(default_factory=dict)


def header_value(headers: Mapping[str, str], name: str) -> str | None:
    """Read a header from either Django's case-insensitive mapping or a plain dict."""
    value = headers.get(name)
    if value is not None:
        return value
    lowered = name.lower()
    for key, candidate in headers.items():
        if key.lower() == lowered:
            return candidate
    return None


def hmac_signature(
    secret: str,
    signed: bytes,
    *,
    digest: HmacDigest = "sha256",
    encoding: SignatureEncoding = "hex",
    prefix: str = "",
) -> str:
    computed = hmac.digest(secret.encode("utf-8"), signed, digest)
    encoded = base64.b64encode(computed).decode("ascii") if encoding == "base64" else computed.hex()
    return prefix + encoded


def hmac_sha256_signature(
    secret: str,
    signed: bytes,
    *,
    encoding: SignatureEncoding = "hex",
    prefix: str = "",
) -> str:
    """The SHA-256 form, which is what every caller of this module signs with."""
    return hmac_signature(secret, signed, digest="sha256", encoding=encoding, prefix=prefix)


def signatures_match(expected: str, provided: str) -> bool:
    # Compared as bytes, because compare_digest raises TypeError on a str that holds a
    # non-ASCII code point, and a header arrives here decoded as latin-1. An unauthenticated
    # caller could otherwise turn a junk header into a 500.
    return hmac.compare_digest(expected.encode("utf-8"), provided.encode("utf-8"))


class SignatureScheme(Protocol):
    def verify(self, *, body: bytes, headers: Mapping[str, str]) -> Verification: ...

    def rejects_headers(self, headers: Mapping[str, str]) -> bool:
        """Whether the headers alone already fail the check, so the body need not be read.

        `WebhookProvider.verify` asks this first, and a `True` answers exactly what an INVALID
        verification answers. A scheme that cannot decide from headers alone answers `False`.
        """
        ...


@frozen
class HmacSignature:
    """A keyed HMAC over the raw body, in the shapes the providers here actually send.

    GitHub sends ``sha256=<hex>``; Slack and Customer.io sign ``v0:{timestamp}:{body}``
    and pair the signature with a timestamp header they expect to be checked for replay.
    `digest` is the hash under the key, and only a provider that leaves no choice sets it
    to anything but the default.
    """

    secret_getter: Callable[[], str | None]
    signature_header: str
    prefix: str = ""
    digest: HmacDigest = "sha256"
    encoding: SignatureEncoding = "hex"
    signed_input: SignedInput = "body"
    timestamp_header: str | None = None
    timestamp_max_age_seconds: int = 300
    timestamp_max_future_seconds: int = 300
    # Cheap shape gate run before the HMAC, so a probe cannot drive digest CPU (Vapi).
    signature_pattern: re.Pattern[str] | None = None

    def _timestamp_is_fresh(self, timestamp: str) -> bool:
        try:
            age_seconds = time.time() - float(timestamp)
        except ValueError:
            return False
        return -self.timestamp_max_future_seconds <= age_seconds <= self.timestamp_max_age_seconds

    def _signed_bytes(self, body: bytes, timestamp: str | None) -> bytes:
        if self.signed_input == "v0_timestamp_body" and timestamp is not None:
            # Assembled as bytes rather than through a decoded string, so a body that is
            # not valid UTF-8 fails the comparison instead of raising.
            return b"v0:" + timestamp.encode("utf-8") + b":" + body
        return body

    def _expected_signature(self, secret: str, signed: bytes) -> str:
        return hmac_signature(secret, signed, digest=self.digest, encoding=self.encoding, prefix=self.prefix)

    def _headers_fail(self, headers: Mapping[str, str]) -> bool:
        provided = header_value(headers, self.signature_header)
        if not provided:
            return True
        if self.signature_pattern is not None and not self.signature_pattern.match(provided):
            return True
        if self.timestamp_header is None:
            return False
        # Freshness needs only the clock, so a malformed or stale timestamp costs no body read either.
        timestamp = header_value(headers, self.timestamp_header)
        return not timestamp or not self._timestamp_is_fresh(timestamp)

    def rejects_headers(self, headers: Mapping[str, str]) -> bool:
        # An unconfigured endpoint keeps answering NOT_CONFIGURED, whatever the headers carry.
        if not self.secret_getter():
            return False
        return self._headers_fail(headers)

    def _outcome(self, *, body: bytes, headers: Mapping[str, str]) -> VerificationOutcome:
        secret = self.secret_getter()
        if not secret:
            return VerificationOutcome.NOT_CONFIGURED
        if self._headers_fail(headers):
            return VerificationOutcome.INVALID

        # Present and well-shaped, because `rejects_headers` just said so.
        provided = header_value(headers, self.signature_header) or ""

        timestamp = header_value(headers, self.timestamp_header) if self.timestamp_header is not None else None

        expected = self._expected_signature(secret, self._signed_bytes(body, timestamp))
        if signatures_match(expected, provided):
            return VerificationOutcome.VERIFIED
        return VerificationOutcome.INVALID

    def verify(self, *, body: bytes, headers: Mapping[str, str]) -> Verification:
        # No facts: an HMAC over the raw body proves the sender holds the secret and says
        # nothing else about the delivery.
        return Verification(outcome=self._outcome(body=body, headers=headers))


@frozen
class HmacSha256(HmacSignature):
    """The SHA-256 form, and the name every provider but one reaches for.

    It exists so that "which digest" is a question only the provider that has to answer it
    ever sees. The digest is fixed here rather than defaulted, so a name that promises
    SHA-256 cannot be handed another one; `HmacSignature` is where a digest is chosen.
    """

    digest: HmacDigest = field(default="sha256", init=False)


@frozen
class SnsSignature:
    """AWS SNS message signature plus a topic-ARN allowlist.

    The signature proves "from AWS SNS" and the allowlist proves "from our topic", so
    neither half is optional. The signature half is the same for every SNS topic and lives
    in `sns_signature.py`, which raises `VerifierUnavailable` when it could not obtain the
    certificate at all; only the allowlist belongs to the endpoint.
    """

    allowed_topic_arns: Callable[[], frozenset[str]]

    def rejects_headers(self, headers: Mapping[str, str]) -> bool:
        # SNS signs the JSON envelope and carries nothing in the headers, so there is no
        # header-only refusal to make here.
        return False

    def _outcome(self, *, body: bytes, headers: Mapping[str, str]) -> VerificationOutcome:
        allowed = self.allowed_topic_arns()
        if not allowed:
            return VerificationOutcome.NOT_CONFIGURED
        try:
            # RecursionError: deeply nested JSON from an unauthenticated caller must not 500.
            message = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
            return VerificationOutcome.INVALID
        if not isinstance(message, dict):
            return VerificationOutcome.INVALID
        if message.get("TopicArn") not in allowed:
            logger.warning("ingress_sns_unknown_topic", topic=message.get("TopicArn"))
            return VerificationOutcome.INVALID
        try:
            verified = verify_sns_message(message)
        except VerifierUnavailable:
            # UNAVAILABLE rather than INVALID: the signature was never checked, and SNS reads
            # the invalid-signature status as a verdict and stops delivering.
            logger.warning("ingress_sns_signing_certificate_unavailable", message_id=message.get("MessageId"))
            return VerificationOutcome.UNAVAILABLE
        if not verified:
            logger.warning("ingress_sns_invalid_signature", message_id=message.get("MessageId"))
            return VerificationOutcome.INVALID
        return VerificationOutcome.VERIFIED

    def verify(self, *, body: bytes, headers: Mapping[str, str]) -> Verification:
        # No facts: the allowlist and the RSA check both read the body the incarnation parses
        # again, so there is nothing here that `deliveries` cannot see for itself.
        return Verification(outcome=self._outcome(body=body, headers=headers))
