"""Stripe request-signature and API-Version verification (APP 0.1d).

Implements the spec's legacy signing scheme only: ``Stripe-Signature:
t=<timestamp>,v1=<hex>`` where the signature is HMAC-SHA256 over
``"{timestamp}.{body}"``, verified against the global
``settings.STRIPE_SIGNING_SECRET`` with a 300s drift tolerance.

Future work: the spec also defines a preferred ``Stripe-Signature-V2`` scheme -
an EdDSA-signed JWT (``alg=EdDSA``, ``typ=JWT``, ``kid``) verified against
Ed25519 keys fetched from ``GET <orchestrator>/v2/provisioning/public_keys``.

When Stripe moves off legacy HMAC, that verification slots in here, next to
``verify_stripe_signature``. See the Authentication section of
https://github.com/agentic-provisioning/posthog-spec/blob/master/docs/spec.md.

The verify helpers return a DRF ``Response`` (flat error envelope) on failure
and ``None`` on success, so views can keep the spec-mandated check ordering
explicit with ``if error := verify_...(request): return error``.
"""

from __future__ import annotations

import hmac
import hashlib

from django.conf import settings
from django.http.request import RawPostDataException

import structlog
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.exceptions_capture import capture_exception

from ee.partners.stripe.api.provisioning.analytics import capture_signature_event
from ee.partners.stripe.api.provisioning.constants import MAX_TIMESTAMP_DRIFT_SECONDS, SUPPORTED_VERSIONS

logger = structlog.get_logger(__name__)


def verify_api_version(request: Request) -> Response | None:
    """Check the API-Version header matches a supported version.

    Returns None if valid, or an error Response if not.
    """
    api_version = request.headers.get("api-version", "")
    if api_version not in SUPPORTED_VERSIONS:
        _log_and_capture_event("invalid_api_version", 400, request.path, api_version=api_version)
        return Response(
            {
                "error": {
                    "code": "invalid_api_version",
                    "message": f"Supported API-Versions: {', '.join(SUPPORTED_VERSIONS)}",
                }
            },
            status=400,
        )
    return None


def verify_stripe_signature(request: Request) -> Response | None:
    """Verify the Stripe-Signature HMAC against the global signing secret.

    Returns None if verification passes, or an error Response if it fails.

    Delegates to the Stripe SDK, which checks the timestamp and every ``v1``
    signature in the header. During a ``STRIPE_SIGNING_SECRET`` rotation the
    sender dual-signs each request, so the header carries the old and new
    signatures at once; matching against any of them keeps verification working
    across the switch-over instead of breaking the moment the secret changes.
    """
    endpoint = request.path

    secret = settings.STRIPE_SIGNING_SECRET
    if not secret:
        _log_and_capture_event("server_error", 500, endpoint)
        return Response({"error": {"code": "server_error", "message": "Signing secret not configured"}}, status=500)

    body = _get_raw_body(request)
    if body is None:
        _log_and_capture_event("body_not_readable", 400, endpoint)
        return Response(
            {
                "error": {
                    "code": "body_not_readable",
                    "message": "Unable to read request body for signature verification",
                }
            },
            status=400,
        )

    try:
        decoded_body = body.decode("utf-8")
    except UnicodeDecodeError as e:
        _log_and_capture_event("body_not_decodable", 400, endpoint, reason=str(e))
        return Response(
            {"error": {"code": "body_not_decodable", "message": "Request body must be UTF-8 encoded"}},
            status=400,
        )

    # Deferred: the stripe SDK is ~0.45s to import and is only needed on this verify path.
    import stripe  # noqa: PLC0415

    sig_header = request.headers.get("stripe-signature", "")
    try:
        stripe.WebhookSignature.verify_header(decoded_body, sig_header, secret, tolerance=MAX_TIMESTAMP_DRIFT_SECONDS)
    except stripe.SignatureVerificationError as e:
        _log_and_capture_event("invalid_signature", 401, endpoint, reason=str(e))
        return Response(
            {"error": {"code": "invalid_signature", "message": "Signature verification failed"}}, status=401
        )

    _log_and_capture_event("success", 200, endpoint)
    return None


def compute_signature(secret: str, timestamp: int, body: bytes) -> str:
    """Compute HMAC-SHA256 signature for a request body. Exposed for testing."""
    mac = hmac.new(secret.encode(), digestmod=hashlib.sha256)
    mac.update(f"{timestamp}.".encode())
    mac.update(body)
    return mac.digest().hex()


def _get_raw_body(request: Request) -> bytes | None:
    """Get raw request body, returning None if the stream was already consumed."""
    django_request = getattr(request, "_request", request)
    if hasattr(django_request, "_body"):
        return django_request._body
    try:
        return django_request.body
    except RawPostDataException:
        capture_exception(
            Exception("Request body stream consumed before signature verification"),
            {"endpoint": request.path},
        )
        logger.exception("signature.stream_consumed", endpoint=request.path)
        return None


def _log_and_capture_event(outcome: str, status_code: int, endpoint: str, **extra: object) -> None:
    log_kwargs = {"outcome": outcome, "status_code": status_code, "endpoint": endpoint, **extra}
    if status_code >= 400:
        logger.warning("signature.verification_failed", **log_kwargs)
    else:
        logger.info("signature.verification_ok", **log_kwargs)

    capture_signature_event(outcome, status_code, endpoint, **extra)
