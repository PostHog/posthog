"""
The AI gateway's low-balance call.

When an organization's AI balance drops below its low-balance threshold, the AI gateway calls this
route once and names the organization in the body. It sends the `AI_GATEWAY_INTERNAL_TOKEN` bearer, as
its generation-request callback does. PostHog asks billing to reload the organization's balance with
its licensed client, and passes billing's answer back. Billing charges the card on file inside the
request, so the call can take tens of seconds. Mounted under /api/internal/, which the public ingress
doesn't expose. The billing client lives in `ee/billing/`, so the view imports it when a call arrives.
"""

import hmac
from typing import Any

from django.conf import settings

import requests
import structlog
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.cloud_utils import get_cached_instance_license
from posthog.models import Organization

logger = structlog.get_logger(__name__)

RETRY = {"detail": "Billing couldn't reload the balance. Retry with the same Idempotency-Key."}


class AIGatewayReloadRequestSerializer(serializers.Serializer):
    organization_id = serializers.UUIDField(
        help_text="The ID of the organization whose AI balance dropped below its low-balance threshold."
    )
    balance_usd = serializers.DecimalField(
        max_digits=20,
        decimal_places=6,
        help_text=(
            'The organization\'s AI balance in USD when it dropped below the threshold, such as "4.104512". '
            "Send at most six decimal places, as the gateway keeps it. Billing rounds only the charge."
        ),
    )


class AIGatewayReloadView(APIView):
    """
    POST /api/internal/ai_gateway/reload: reload the AI balance of the organization in the body.

    Send an `Idempotency-Key` header, the same one on every retry of one low-balance crossing. A retry
    gets the first answer and charges nothing more. Answers:

    - 200 `{"result": "charged", "amount_usd": "45.90"}` or `{"result": "declined", "reason": "reload_off"}`.
    - 409 while billing charges a reload for the organization. Nothing more is charged.
    - 401 when the bearer token isn't the gateway's.
    - 403 when the organization doesn't buy AI credits.
    - 503 when billing couldn't finish. Retry with the same key.
    """

    # The view checks the gateway's token itself, so DRF authenticates nobody.
    authentication_classes = []
    permission_classes = []

    def post(self, request: Request) -> Response:
        if not _sent_the_gateway_token(request):
            return Response({"detail": "Invalid service credential"}, status=status.HTTP_401_UNAUTHORIZED)
        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key:
            return Response({"detail": "Send an Idempotency-Key header"}, status=status.HTTP_400_BAD_REQUEST)
        serializer = AIGatewayReloadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        organization = Organization.objects.filter(id=serializer.validated_data["organization_id"]).first()
        if organization is None:
            return Response({"detail": "Organization not found"}, status=status.HTTP_404_NOT_FOUND)

        from ee.billing.billing_manager import BillingManager, BillingServiceResponseError  # noqa: PLC0415

        try:
            answer = BillingManager(get_cached_instance_license()).reload_ai_balance(
                organization,
                idempotency_key=idempotency_key,
                balance_usd=str(serializer.validated_data["balance_usd"]),
            )
        except BillingServiceResponseError as error:
            return _refusal(error.status_code, organization)
        except requests.RequestException:
            logger.exception("ai_gateway_reload_billing_unreachable", organization_id=str(organization.id))
            return Response(RETRY, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(_answer(answer))


def _sent_the_gateway_token(request: Request) -> bool:
    expected = settings.AI_GATEWAY_INTERNAL_TOKEN or ""
    authorization = request.headers.get("Authorization", "")
    prefix = "Bearer "
    token = authorization[len(prefix) :] if authorization.startswith(prefix) else ""
    return bool(expected) and hmac.compare_digest(token.encode(), expected.encode())


def _answer(answer: dict[str, Any]) -> dict[str, Any]:
    # Only the fields the gateway reads, so a change in billing's answer doesn't reach the gateway.
    if answer.get("result") == "charged":
        return {"result": "charged", "amount_usd": answer.get("amount_usd")}
    return {"result": "declined", "reason": answer.get("reason")}


def _refusal(billing_status: int, organization: Organization) -> Response:
    if billing_status == status.HTTP_409_CONFLICT:
        return Response({"detail": "A reload for this organization is running"}, status=status.HTTP_409_CONFLICT)
    if billing_status == status.HTTP_403_FORBIDDEN:
        return Response({"detail": "This organization doesn't buy AI credits"}, status=status.HTTP_403_FORBIDDEN)
    logger.error("ai_gateway_reload_billing_refused", organization_id=str(organization.id), status=billing_status)
    return Response(RETRY, status=status.HTTP_503_SERVICE_UNAVAILABLE)
