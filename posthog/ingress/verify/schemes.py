"""Signature schemes: the part of a provider incarnation that decides "this is really them"."""

import re
import hmac
import json
import time
import base64
from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Any, Literal, Protocol

import structlog

from posthog.dataclasses import frozen

logger = structlog.get_logger(__name__)

SignedInput = Literal["body", "v0_timestamp_body"]
SignatureEncoding = Literal["hex", "base64"]


class VerificationOutcome(StrEnum):
    VERIFIED = "verified"
    INVALID = "invalid"
    # The instance holds no secret for this provider app, which is an operator problem
    # rather than a caller one, so incarnations answer it with their own status code.
    NOT_CONFIGURED = "not_configured"


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


def hmac_sha256_signature(
    secret: str,
    signed: bytes,
    *,
    encoding: SignatureEncoding = "hex",
    prefix: str = "",
) -> str:
    digest = hmac.digest(secret.encode("utf-8"), signed, "sha256")
    encoded = base64.b64encode(digest).decode("ascii") if encoding == "base64" else digest.hex()
    return prefix + encoded


def signatures_match(expected: str, provided: str) -> bool:
    # Compared as bytes, because compare_digest raises TypeError on a str that holds a
    # non-ASCII code point, and a header arrives here decoded as latin-1. An unauthenticated
    # caller could otherwise turn a junk header into a 500.
    return hmac.compare_digest(expected.encode("utf-8"), provided.encode("utf-8"))


class SignatureScheme(Protocol):
    def verify(self, *, body: bytes, headers: Mapping[str, str]) -> VerificationOutcome: ...


@frozen
class HmacSha256:
    """HMAC-SHA256 over the raw body, in the shapes the providers here actually send.

    GitHub sends ``sha256=<hex>``; Slack and Customer.io sign ``v0:{timestamp}:{body}``
    and pair the signature with a timestamp header they expect to be checked for replay.
    """

    secret_getter: Callable[[], str | None]
    signature_header: str
    prefix: str = ""
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
        return hmac_sha256_signature(secret, signed, encoding=self.encoding, prefix=self.prefix)

    def verify(self, *, body: bytes, headers: Mapping[str, str]) -> VerificationOutcome:
        secret = self.secret_getter()
        if not secret:
            return VerificationOutcome.NOT_CONFIGURED

        provided = header_value(headers, self.signature_header)
        if not provided:
            return VerificationOutcome.INVALID
        if self.signature_pattern is not None and not self.signature_pattern.match(provided):
            return VerificationOutcome.INVALID

        timestamp: str | None = None
        if self.timestamp_header is not None:
            timestamp = header_value(headers, self.timestamp_header)
            if not timestamp or not self._timestamp_is_fresh(timestamp):
                return VerificationOutcome.INVALID

        expected = self._expected_signature(secret, self._signed_bytes(body, timestamp))
        if signatures_match(expected, provided):
            return VerificationOutcome.VERIFIED
        return VerificationOutcome.INVALID


@frozen
class SnsSignature:
    """AWS SNS message signature plus a topic-ARN allowlist.

    The signature proves "from AWS SNS" and the allowlist proves "from our topic", so
    neither half is optional. The RSA work stays with the caller-supplied verifier, which
    owns the certificate fetch and its own cache.
    """

    verify_message: Callable[[Mapping[str, Any]], bool]
    allowed_topic_arns: Callable[[], frozenset[str]]

    def verify(self, *, body: bytes, headers: Mapping[str, str]) -> VerificationOutcome:
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
        if not self.verify_message(message):
            logger.warning("ingress_sns_invalid_signature", message_id=message.get("MessageId"))
            return VerificationOutcome.INVALID
        return VerificationOutcome.VERIFIED
