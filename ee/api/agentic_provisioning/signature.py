import re
import hmac
import time
import uuid
import hashlib

from django.conf import settings
from django.http.request import RawPostDataException

import structlog
import posthoganalytics
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.exceptions_capture import capture_exception

logger = structlog.get_logger(__name__)

SUPPORTED_VERSIONS = ["0.1d"]
API_VERSION = SUPPORTED_VERSIONS[0]
SIGNATURE_HEADER = "Stripe-Signature"
API_VERSION_HEADER = "API-Version"
MAX_TIMESTAMP_DRIFT_SECONDS = 300


def verify_api_version(request: Request) -> Response | None:
    """Check the API-Version header matches a supported version.

    Returns None if valid, or an error Response if not.
    """
    api_version = request.headers.get("api-version", "")
    if api_version not in SUPPORTED_VERSIONS:
        endpoint = request.path
        _log_and_capture_event("invalid_api_version", 400, endpoint, api_version=api_version)
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


def verify_provisioning_signature(request: Request) -> Response | None:
    """Verify the Stripe-Signature HMAC.

    Returns None if verification passes, or an error Response if it fails.
    Called at the top of every view (Vercel-style, not middleware).
    """
    endpoint = request.path

    secret = settings.STRIPE_SIGNING_SECRET
    if not secret:
        _log_and_capture_event("server_error", 500, endpoint)
        return Response({"error": {"code": "server_error", "message": "Signing secret not configured"}}, status=500)

    sig_header = request.headers.get("stripe-signature", "")
    parsed = _parse_signature_header(sig_header)
    if parsed is None:
        _log_and_capture_event("invalid_signature", 401, endpoint, reason="missing_or_malformed_header")
        return Response(
            {"error": {"code": "invalid_signature", "message": "Missing or malformed Stripe-Signature header"}},
            status=401,
        )

    timestamp_str, signature_hex = parsed

    now = int(time.time())
    timestamp = int(timestamp_str)
    if abs(now - timestamp) > MAX_TIMESTAMP_DRIFT_SECONDS:
        _log_and_capture_event(
            "invalid_signature", 401, endpoint, reason="timestamp_drift", drift_seconds=abs(now - timestamp)
        )
        return Response(
            {"error": {"code": "invalid_signature", "message": "Timestamp too old or too far in the future"}},
            status=401,
        )

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

    expected_hex = _compute_hmac(secret, timestamp_str, body)

    if not hmac.compare_digest(expected_hex.lower(), signature_hex.lower()):
        _log_and_capture_event("invalid_signature", 401, endpoint, reason="hmac_mismatch")
        return Response(
            {"error": {"code": "invalid_signature", "message": "Signature verification failed"}}, status=401
        )

    _log_and_capture_event("success", 200, endpoint)
    return None


def compute_signature(secret: str, timestamp: int, body: bytes) -> str:
    """Compute HMAC-SHA256 signature for a request body. Exposed for testing."""
    return _compute_hmac(secret, str(timestamp), body)


def _compute_hmac(signing_key: str, timestamp_str: str, body: bytes) -> str:
    mac = hmac.new(signing_key.encode(), digestmod=hashlib.sha256)
    mac.update(f"{timestamp_str}.".encode())
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

    posthoganalytics.capture(
        "agentic_provisioning signature verification",
        distinct_id=f"agentic_provisioning_{uuid.uuid4().hex[:16]}",
        properties={"outcome": outcome, "status_code": status_code, "endpoint": endpoint, **extra},
    )


_SIG_RE = re.compile(r"t=(\d+),v1=([0-9a-fA-F]{64})")


def _parse_signature_header(header: str) -> tuple[str, str] | None:
    """Parse 't=<timestamp>,v1=<hex>' into (timestamp_str, hex). Returns None on failure."""
    m = _SIG_RE.search(header)
    if not m:
        return None
    return m.group(1), m.group(2)
