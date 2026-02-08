import hmac
import hashlib
from typing import Any

from django.conf import settings

import structlog
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.exceptions_capture import capture_exception
from posthog.models.organization_integration import OrganizationIntegration

from ee.billing.billing_manager import BillingManager
from ee.models import License

logger = structlog.get_logger(__name__)

BILLING_EVENT_PREFIX = "marketplace.invoice."


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


def _extract_config_id(payload: dict[str, Any]) -> str | None:
    # Ref: https://vercel.com/docs/observability/webhooks-overview/webhooks-api
    return payload.get("installationId")


def _is_billing_event(event_type: str | None) -> bool:
    return bool(event_type and event_type.startswith(BILLING_EVENT_PREFIX))


def _get_integration(config_id: str) -> OrganizationIntegration | None:
    try:
        return OrganizationIntegration.objects.select_related("organization").get(
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id=config_id,
        )
    except OrganizationIntegration.DoesNotExist:
        return None


def _forward_to_billing_service(event_type: str, payload: dict[str, Any], integration: OrganizationIntegration) -> None:
    license = License.objects.first()
    if not license:
        raise ValueError("No license configured")

    billing_manager = BillingManager(license=license)
    billing_manager.handle_billing_provider_webhook(
        event_type=event_type,
        event_data=payload,
        organization=integration.organization,
        billing_provider="vercel",
    )


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

    event_type = request.data.get("type")
    payload = request.data.get("payload", {})
    config_id = _extract_config_id(payload)

    logger.info("vercel_webhook_received", event_type=event_type, config_id=config_id)

    if not _is_billing_event(event_type):
        logger.info("vercel_webhook_non_billing_event", event_type=event_type)
        return Response({"status": "ignored"}, status=status.HTTP_200_OK)

    if not config_id:
        logger.error("vercel_webhook_missing_config_id", event_type=event_type)
        return Response({"error": "Missing configurationId"}, status=status.HTTP_400_BAD_REQUEST)

    assert event_type is not None  # Guaranteed by _is_billing_event check above

    integration = _get_integration(config_id)
    if not integration:
        logger.error("vercel_webhook_unknown_config", config_id=config_id)
        capture_exception(
            OrganizationIntegration.DoesNotExist(),
            {"config_id": config_id, "event_type": event_type},
        )
        return Response({"error": "Unknown configuration"}, status=status.HTTP_404_NOT_FOUND)

    try:
        _forward_to_billing_service(event_type, payload, integration)
    except Exception as e:
        logger.exception("vercel_webhook_billing_error", event_type=event_type)
        capture_exception(e, {"config_id": config_id, "event_type": event_type})
        return Response({"error": "Processing failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    logger.info("vercel_webhook_processed", event_type=event_type, org_id=str(integration.organization_id))
    return Response({"status": "ok"}, status=status.HTTP_200_OK)
