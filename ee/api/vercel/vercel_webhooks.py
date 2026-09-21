import hmac
import hashlib

from django.conf import settings

import structlog
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.exceptions_capture import capture_exception

from ee.api.vercel.webhook_events import VercelEventOutcome, VercelEventProcessingError, handle_vercel_event

logger = structlog.get_logger(__name__)


def _is_valid_signature(payload: bytes, signature: str | None) -> bool:
    if not signature:
        return False

    secret = getattr(settings, "VERCEL_CLIENT_INTEGRATION_SECRET", None)
    if not secret:
        logger.error("vercel_webhook_missing_secret")
        capture_exception(Exception("VERCEL_CLIENT_INTEGRATION_SECRET not configured"), {})
        return False

    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha1).hexdigest()
    return hmac.compare_digest(expected, signature)


# The outcomes the handling reports, and what each one answers Vercel.
_OUTCOME_RESPONSES = {
    VercelEventOutcome.ACCEPTED: ({"status": "ok"}, status.HTTP_200_OK),
    VercelEventOutcome.IGNORED: ({"status": "ignored"}, status.HTTP_200_OK),
    VercelEventOutcome.MISSING_CONFIG_ID: ({"error": "Missing configurationId"}, status.HTTP_400_BAD_REQUEST),
    VercelEventOutcome.UNKNOWN_CONFIG: ({"error": "Unknown configuration"}, status.HTTP_404_NOT_FOUND),
}


@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
def vercel_webhook(request: Request) -> Response:
    """
    Handle Vercel webhooks. Routes billing events (marketplace.invoice.*) to the billing service.
    Non-billing events are acknowledged but not processed.
    """
    signature = request.headers.get("x-vercel-signature")
    if not _is_valid_signature(request.body, signature):
        logger.warning("vercel_webhook_invalid_signature")
        return Response({"error": "Invalid signature"}, status=status.HTTP_401_UNAUTHORIZED)

    try:
        outcome = handle_vercel_event(
            event_type=request.data.get("type"),
            payload=request.data.get("payload", {}),
            raw_body=request.body,
            signature=signature,
        )
    except VercelEventProcessingError:
        return Response({"error": "Processing failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    body, response_status = _OUTCOME_RESPONSES[outcome]
    return Response(body, status=response_status)
