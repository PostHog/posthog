"""
The AI gateway's low-balance call.

When an organization's AI balance reaches its low-balance threshold, the AI gateway posts a signed reload
request to this route. It sends the `AI_GATEWAY_INTERNAL_TOKEN` bearer, as its generation-request callback does.
PostHog checks the token and reads the organization from the signed body. It posts the envelope unchanged to
billing with its licensed client, and passes billing's answer back. PostHog holds no signing key, so billing
checks the signature. Billing starts its reload and answers before it charges anything. The outcome comes back
later on billing's queue, and PostHog relays it to the gateway.
Mounted under /api/internal/, which the public ingress doesn't expose. The billing client lives in `ee/billing/`,
so the view imports it when a call arrives.
"""

import hmac
from typing import Any

from django.conf import settings

import requests
import structlog
from rest_framework import serializers, status
from rest_framework.parsers import JSONParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.cloud_utils import get_cached_instance_license
from posthog.llm.gateway_internal_client import MalformedSignedMessage, read_signed_message
from posthog.models import Organization

logger = structlog.get_logger(__name__)

AI_RELOAD_REQUESTED = "ai_reload_requested"
RETRY = {"detail": "Billing couldn't start the reload. Ask again with the same reload key."}


class AIGatewayReloadRequestSerializer(serializers.Serializer):
    body = serializers.CharField(
        trim_whitespace=False,
        help_text=(
            "The message that you signed, as the exact JSON string that you signed. Set `type` to "
            "`ai_reload_requested` and `organization_id` to the organization whose AI balance reached its "
            "low-balance threshold. Set a new `reload_key` for each crossing, and send the same key to ask again."
        ),
    )
    signed_at = serializers.CharField(
        trim_whitespace=False,
        help_text='The UTC time of the signature in whole seconds, such as "2026-11-23T18:04:05Z".',
    )
    key_id = serializers.CharField(trim_whitespace=False, help_text="The ID of the key that made the signature.")
    signature = serializers.CharField(
        trim_whitespace=False,
        help_text=(
            "The HMAC-SHA256 of `signed_at`, a period and `body`, under the key that `key_id` names. "
            "Send it in lowercase hex."
        ),
    )


class AIGatewayReloadView(APIView):
    """
    POST /api/internal/ai_gateway/reload: reload the AI balance of the organization in the signed body.

    Send the envelope as the JSON body. A request again with the same reload key starts nothing new. Answers:

    - 202 `{"result": "accepted"}` when billing starts the reload. The outcome follows on billing's
      queue, which PostHog relays to the gateway's reload-outcome route.
    - 400 when PostHog can't read the envelope, or the body's type isn't `ai_reload_requested`.
    - 401 when the bearer token isn't the gateway's.
    - 403 when the organization doesn't buy AI credits.
    - 404 when PostHog doesn't know the organization.
    - 503 when billing couldn't start the reload. Ask again with the same reload key.
    """

    # The view checks the gateway's token itself, so DRF authenticates nobody.
    authentication_classes = []
    permission_classes = []
    # A form body has no single string for each field, so PostHog couldn't send it on unchanged.
    parser_classes = [JSONParser]

    def post(self, request: Request) -> Response:
        if not _sent_the_gateway_token(request):
            return Response({"detail": "Invalid service credential"}, status=status.HTTP_401_UNAUTHORIZED)
        AIGatewayReloadRequestSerializer(data=request.data).is_valid(raise_exception=True)
        try:
            message = read_signed_message(request.data)
        except MalformedSignedMessage as error:
            return Response({"detail": f"Send a readable envelope: {error}"}, status=status.HTTP_400_BAD_REQUEST)
        if message.type != AI_RELOAD_REQUESTED:
            return Response(
                {"detail": f"Send a body whose type is {AI_RELOAD_REQUESTED}"}, status=status.HTTP_400_BAD_REQUEST
            )
        organization = Organization.objects.filter(id=message.organization_id).first()
        if organization is None:
            return Response({"detail": "Organization not found"}, status=status.HTTP_404_NOT_FOUND)

        from ee.billing.billing_manager import BillingManager, BillingServiceResponseError  # noqa: PLC0415

        try:
            answer = BillingManager(get_cached_instance_license()).reload_ai_balance(organization, message.envelope)
        except BillingServiceResponseError as error:
            return _refusal(error.status_code, organization)
        except requests.RequestException:
            logger.exception("ai_gateway_reload_billing_unreachable", organization_id=str(organization.id))
            return Response(RETRY, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(_answer(answer), status=status.HTTP_202_ACCEPTED)


def _sent_the_gateway_token(request: Request) -> bool:
    expected = settings.AI_GATEWAY_INTERNAL_TOKEN or ""
    authorization = request.headers.get("Authorization", "")
    prefix = "Bearer "
    token = authorization[len(prefix) :] if authorization.startswith(prefix) else ""
    return bool(expected) and hmac.compare_digest(token.encode(), expected.encode())


def _answer(answer: dict[str, Any]) -> dict[str, Any]:
    # Only the field the gateway reads, so a change in billing's answer doesn't reach the gateway.
    return {"result": answer.get("result")}


def _refusal(billing_status: int, organization: Organization) -> Response:
    if billing_status == status.HTTP_403_FORBIDDEN:
        return Response({"detail": "This organization doesn't buy AI credits"}, status=status.HTTP_403_FORBIDDEN)
    logger.error("ai_gateway_reload_billing_refused", organization_id=str(organization.id), status=billing_status)
    return Response(RETRY, status=status.HTTP_503_SERVICE_UNAVAILABLE)
