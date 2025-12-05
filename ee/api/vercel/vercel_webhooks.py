"""
Vercel Webhook Handler

Receives webhooks from Vercel and routes billing events to the billing service.
PostHog acts as a pure passthrough - no event normalization, no business logic.
The billing service owns all billing provider event handling.

Webhook events handled:
- marketplace.invoice.paid (this slice) - Customer paid invoice
- marketplace.invoice.created (Slice 5) - Invoice created
- marketplace.invoice.notpaid (Slice 5) - Invoice not paid after grace period
- marketplace.invoice.refunded (Slice 5) - Invoice refunded
"""

import hmac
import hashlib

from django.conf import settings
from django.views.decorators.csrf import csrf_exempt

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

BILLING_EVENT_PREFIX = "marketplace."


def verify_vercel_webhook_signature(payload: bytes, signature: str | None) -> bool:
    """
    Verify the webhook signature from Vercel using HMAC-SHA1.

    Vercel signs webhooks using HMAC-SHA1 with the client integration secret.
    The signature is provided in the x-vercel-signature header.
    """
    if not signature:
        return False

    secret = getattr(settings, "VERCEL_CLIENT_INTEGRATION_SECRET", None)
    if not secret:
        logger.error("vercel_webhook_missing_secret", error="VERCEL_CLIENT_INTEGRATION_SECRET not configured")
        return False

    expected_signature = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha1,
    ).hexdigest()

    return hmac.compare_digest(expected_signature, signature)


@csrf_exempt
@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
def vercel_webhook(request: Request) -> Response:
    """
    Receives webhooks from Vercel.

    Routes billing events (marketplace.*) to the billing service.
    Non-billing events are acknowledged but not processed.
    """
    # 1. Verify webhook signature
    signature = request.headers.get("x-vercel-signature")
    if not verify_vercel_webhook_signature(request.body, signature):
        logger.warning("vercel_webhook_invalid_signature")
        return Response({"error": "Invalid signature"}, status=status.HTTP_401_UNAUTHORIZED)

    # 2. Parse event
    event_type = request.data.get("type")
    payload = request.data.get("payload", {})

    # configurationId location varies by event type:
    # - marketplace.invoice.* events: inside payload as installationId or configuration.id
    # - other events: configurationId at top level
    config_id = (
        request.data.get("configurationId")
        or payload.get("installationId")
        or payload.get("configuration", {}).get("id")
        or payload.get("configurationId")
    )

    logger.info("vercel_webhook_received", event_type=event_type, config_id=config_id)

    if not config_id:
        logger.error("vercel_webhook_missing_config_id", event_type=event_type)
        return Response({"error": "Missing configurationId"}, status=status.HTTP_400_BAD_REQUEST)

    # 3. Only route billing events to billing service
    if not event_type or not event_type.startswith(BILLING_EVENT_PREFIX):
        logger.info("vercel_webhook_non_billing_event", event_type=event_type)
        return Response({"status": "ignored"}, status=status.HTTP_200_OK)

    # 4. Look up organization
    try:
        integration = OrganizationIntegration.objects.select_related("organization").get(
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id=config_id,
        )
    except OrganizationIntegration.DoesNotExist as e:
        logger.exception("vercel_webhook_unknown_config", config_id=config_id)
        capture_exception(e, {"config_id": config_id, "event_type": event_type})
        return Response({"error": "Unknown configuration"}, status=status.HTTP_404_NOT_FOUND)

    # 5. Forward to billing service (passthrough - no normalization)
    try:
        license = License.objects.first()
        if not license:
            logger.error("vercel_webhook_no_license")
            return Response({"error": "No license configured"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        billing_manager = BillingManager(license=license)
        billing_manager.handle_billing_provider_webhook(
            event_type=event_type,
            event_data=payload,
            organization=integration.organization,
            billing_provider="vercel",
        )
    except Exception as e:
        logger.exception("vercel_webhook_billing_error", event_type=event_type, error=str(e))
        capture_exception(e, {"config_id": config_id, "event_type": event_type})
        # Return 500 so Vercel retries
        return Response({"error": "Processing failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    logger.info(
        "vercel_webhook_processed",
        event_type=event_type,
        org_id=str(integration.organization_id),
    )
    return Response({"status": "ok"}, status=status.HTTP_200_OK)
