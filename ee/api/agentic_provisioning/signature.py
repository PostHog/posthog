import re
import hmac
import time
import hashlib
import logging

from django.conf import settings
from django.http.request import RawPostDataException

from rest_framework.request import Request
from rest_framework.response import Response

logger = logging.getLogger(__name__)

SUPPORTED_VERSIONS = ["0.1d"]
API_VERSION = SUPPORTED_VERSIONS[0]
SIGNATURE_HEADER = "Stripe-Signature"
API_VERSION_HEADER = "API-Version"
MAX_TIMESTAMP_DRIFT_SECONDS = 300


def verify_stripe_signature(request: Request) -> Response | None:
    """Verify the Stripe-Signature HMAC and API-Version header.

    Returns None if verification passes, or an error Response if it fails.
    Called at the top of every view (Vercel-style, not middleware).
    """
    api_version = request.META.get("HTTP_API_VERSION", "")
    if api_version not in SUPPORTED_VERSIONS:
        return Response(
            {
                "error": {
                    "code": "invalid_api_version",
                    "message": f"Supported API-Versions: {', '.join(SUPPORTED_VERSIONS)}",
                }
            },
            status=400,
        )

    secret = settings.STRIPE_APP_SECRET_KEY
    if not secret:
        return Response({"error": {"code": "server_error", "message": "Signing secret not configured"}}, status=500)

    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    parsed = _parse_signature_header(sig_header)
    if parsed is None:
        return Response(
            {"error": {"code": "invalid_signature", "message": "Missing or malformed Stripe-Signature header"}},
            status=401,
        )

    timestamp_str, signature_hex = parsed

    now = int(time.time())
    timestamp = int(timestamp_str)
    if abs(now - timestamp) > MAX_TIMESTAMP_DRIFT_SECONDS:
        return Response(
            {"error": {"code": "invalid_signature", "message": "Timestamp too old or too far in the future"}},
            status=401,
        )

    body = _get_raw_body(request)
    expected_hex = _compute_hmac(secret, timestamp_str, body)

    if not hmac.compare_digest(expected_hex.lower(), signature_hex.lower()):
        return Response(
            {"error": {"code": "invalid_signature", "message": "Signature verification failed"}}, status=401
        )

    return None


def compute_signature(secret: str, timestamp: int, body: bytes) -> str:
    """Compute HMAC-SHA256 signature for a request body. Exposed for testing."""
    return _compute_hmac(secret, str(timestamp), body)


def _compute_hmac(secret: str, timestamp_str: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), digestmod=hashlib.sha256)
    mac.update(f"{timestamp_str}.".encode())
    mac.update(body)
    return mac.digest().hex()


def _get_raw_body(request: Request) -> bytes:
    """Get raw request body, resilient to DRF stream consumption.

    DRF's default throttle classes can access request.data (via
    PersonalAPIKeyAuthentication.find_key_with_source) during
    check_throttles(), which consumes the WSGI input stream. After that,
    HttpRequest.body raises RawPostDataException because _read_started is
    True but _body was never cached.

    This helper tries the underlying Django request's cached _body first,
    falls back to .body, and handles the exception gracefully.
    """
    django_request = getattr(request, "_request", request)
    if hasattr(django_request, "_body"):
        return django_request._body
    try:
        return django_request.body
    except RawPostDataException:
        logger.warning("agentic_provisioning.signature.stream_consumed: request body unavailable for HMAC verification")
        return b""


_SIG_RE = re.compile(r"t=(\d+),v1=([0-9a-fA-F]{64})")


def _parse_signature_header(header: str) -> tuple[str, str] | None:
    """Parse 't=<timestamp>,v1=<hex>' into (timestamp_str, hex). Returns None on failure."""
    m = _SIG_RE.search(header)
    if not m:
        return None
    return m.group(1), m.group(2)
