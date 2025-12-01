from typing import Any

import requests
import structlog
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.models.organization_integration import OrganizationIntegration

from ee.api.authentication import BillingServiceAuthentication

logger = structlog.get_logger(__name__)

VERCEL_API_BASE_URL = "https://api.vercel.com"
REQUEST_TIMEOUT_SECONDS = 30


class VercelProxyRequestSerializer(serializers.Serializer):
    path = serializers.CharField(help_text="The Vercel API path to call (e.g., '/billing/invoices')")
    method = serializers.ChoiceField(
        choices=["GET", "POST", "PUT", "PATCH", "DELETE"],
        help_text="HTTP method to use",
    )
    body = serializers.JSONField(required=False, default=dict, help_text="Request body to send to Vercel")


def _extract_access_token(integration: OrganizationIntegration) -> str:
    """Extract Vercel access token from integration config."""
    token = integration.config.get("credentials", {}).get("access_token")
    if not token:
        raise ValueError(f"No access token found for integration {integration.integration_id}")
    return token


def forward_to_vercel(config_id: str, access_token: str, path: str, method: str, body: dict) -> requests.Response:
    """Forward request to Vercel API."""
    if not path.startswith("/") or ".." in path:
        raise ValueError(f"Invalid path format: {path}")
    url = f"{VERCEL_API_BASE_URL}/v1/installations/{config_id}{path}"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    response = requests.request(
        method=method,
        url=url,
        headers=headers,
        json=body if body else None,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    return response


class VercelProxyViewSet(viewsets.ViewSet):
    """
    Generic proxy endpoint for the billing service to call Vercel APIs.

    The billing service sends requests here with the Vercel API path and body.
    PostHog validates the JWT, looks up the Vercel token from OrganizationIntegration,
    and forwards the request to Vercel.
    """

    authentication_classes = [BillingServiceAuthentication]
    permission_classes = [AllowAny]

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        POST /api/vercel/proxy

        Request body:
        {
            "path": "/billing/invoices",
            "method": "POST",
            "body": { ... vercel payload ... }
        }
        """
        serializer = VercelProxyRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        path = serializer.validated_data["path"]
        method = serializer.validated_data["method"]
        body = serializer.validated_data.get("body", {})

        organization_id = request.user.organization_id

        try:
            integration = OrganizationIntegration.objects.get(
                organization_id=organization_id,
                kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            )
        except OrganizationIntegration.DoesNotExist:
            logger.warning(
                "Vercel integration not found for organization",
                organization_id=organization_id,
            )
            return Response(
                {"error": "No Vercel integration found for this organization"},
                status=status.HTTP_404_NOT_FOUND,
            )

        config_id = integration.integration_id

        try:
            access_token = _extract_access_token(integration)
        except ValueError:
            logger.exception(
                "Failed to extract Vercel access token",
                organization_id=organization_id,
                config_id=config_id,
            )
            return Response(
                {"error": "Failed to retrieve Vercel credentials"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        logger.info(
            "Vercel API proxy request",
            config_id=config_id,
            path=path,
            method=method,
        )

        try:
            vercel_response = forward_to_vercel(
                config_id=config_id,
                access_token=access_token,
                path=path,
                method=method,
                body=body,
            )
        except requests.RequestException:
            logger.exception(
                "Vercel API proxy request failed",
                config_id=config_id,
                path=path,
            )
            return Response(
                {"error": "Failed to reach Vercel API"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if vercel_response.ok:
            logger.info(
                "Vercel API proxy request succeeded",
                config_id=config_id,
                path=path,
                status_code=vercel_response.status_code,
            )
        else:
            logger.error(
                "Vercel API proxy request failed",
                config_id=config_id,
                path=path,
                status_code=vercel_response.status_code,
                response_text=vercel_response.text[:500],
            )

        try:
            response_data = vercel_response.json()
        except requests.JSONDecodeError:
            response_data = {"raw_response": vercel_response.text}

        return Response(response_data, status=vercel_response.status_code)
