import hmac
import hashlib
from typing import Any

from django.conf import settings

import structlog
from rest_framework import exceptions, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.cloud_utils import get_cached_instance_license
from posthog.exceptions_capture import capture_exception
from posthog.models.organization_integration import OrganizationIntegration

from ee.billing.billing_manager import BillingManager

logger = structlog.get_logger(__name__)

EVENT_MAPPING = {
    "marketplace.invoice.paid": "invoice.paid",
    "marketplace.invoice.not_paid": "invoice.not_paid",
    "marketplace.invoice.refunded": "invoice.refunded",
    "integration-configuration.removed": "installation.removed",
}


class VercelWebhookViewSet(viewsets.ViewSet):
    """
    Handle webhooks from Vercel for payment events.

    Flow: Vercel webhook -> PostHog (routing) -> Billing Service (processing)
    """

    authentication_classes = []
    permission_classes = []

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            self._verify_signature(request)
        except exceptions.AuthenticationFailed as e:
            logger.warning("Webhook signature verification failed", error=str(e))
            return Response({"error": "Invalid signature"}, status=status.HTTP_401_UNAUTHORIZED)

        event_type = request.data.get("type")
        payload = request.data.get("payload", {})
        config_id = payload.get("configurationId") or request.data.get("configurationId")

        if not config_id or not event_type:
            return self._bad_request("Missing configurationId or event type")

        normalized_event = EVENT_MAPPING.get(event_type)
        if not normalized_event:
            logger.info("Ignoring unhandled webhook event", event_type=event_type, config_id=config_id)
            return Response({"status": "ignored"}, status=status.HTTP_200_OK)

        try:
            integration = self._get_integration(config_id)
        except OrganizationIntegration.DoesNotExist:
            logger.warning("Webhook for unknown installation", config_id=config_id, event_type=event_type)
            return Response({"error": "Installation not found"}, status=status.HTTP_404_NOT_FOUND)

        return self._forward_to_billing_service(integration, normalized_event, payload, config_id)

    def _verify_signature(self, request: Request) -> None:
        signature = request.headers.get("x-vercel-signature")
        if not signature:
            raise exceptions.AuthenticationFailed("Missing webhook signature")

        client_secret = getattr(settings, "VERCEL_CLIENT_INTEGRATION_SECRET", None)
        if not client_secret:
            logger.error("VERCEL_CLIENT_INTEGRATION_SECRET not configured")
            raise exceptions.AuthenticationFailed("Webhook verification not configured")

        expected = hmac.new(client_secret.encode("utf-8"), request.body, hashlib.sha256).hexdigest()

        if not hmac.compare_digest(signature, expected):
            raise exceptions.AuthenticationFailed("Invalid webhook signature")

    def _get_integration(self, config_id: str) -> OrganizationIntegration:
        return OrganizationIntegration.objects.get(
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id=config_id,
        )

    def _forward_to_billing_service(
        self,
        integration: OrganizationIntegration,
        event_type: str,
        payload: dict,
        config_id: str,
    ) -> Response:
        org_id = str(integration.organization_id)

        logger.info(
            "Processing webhook",
            event_type=event_type,
            config_id=config_id,
            organization_id=org_id,
        )

        try:
            license = get_cached_instance_license()
            if not license:
                raise exceptions.APIException("Billing not configured")

            billing_manager = BillingManager(license)
            billing_manager.handle_marketplace_webhook(
                event_type=event_type,
                event_data=payload,
                organization=integration.organization,
            )

            logger.info("Webhook processed successfully", event_type=event_type, config_id=config_id)
            return Response({"status": "processed"}, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception("Webhook processing failed", event_type=event_type, config_id=config_id, error=str(e))
            capture_exception(e)
            return Response({"error": "Processing failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _bad_request(self, message: str) -> Response:
        logger.warning(message)
        return Response({"error": message}, status=status.HTTP_400_BAD_REQUEST)
