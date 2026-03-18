import urllib.parse
from typing import Any, cast

import requests
import structlog
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.exceptions_capture import capture_exception
from posthog.models.organization_integration import OrganizationIntegration

from ee.api.authentication import BillingServiceAuthentication, BillingServiceUser

logger = structlog.get_logger(__name__)

ALLOWED_VERCEL_PATHS = frozenset(
    [
        "/billing",
        "/billing/invoices",
        "/billing/usage",
    ]
)

ALLOWED_VERCEL_PATH_PREFIXES = (
    "/billing/invoices/",  # GET /billing/invoices/{invoiceId}
)

VERCEL_API_BASE_URL = "https://api.vercel.com"
REQUEST_TIMEOUT_SECONDS = 30


class VercelProxyRequestSerializer(serializers.Serializer):
    path = serializers.CharField(help_text="The Vercel API path to call (e.g., '/billing/invoices')")
    method = serializers.ChoiceField(
        choices=["GET", "POST", "PUT", "PATCH", "DELETE"],
        help_text="HTTP method to use",
    )
    body = serializers.JSONField(required=False, default=dict, help_text="Request body to send to Vercel")

    def validate_path(self, value: str) -> str:
        normalized = urllib.parse.unquote(value)

        if not normalized.startswith("/"):
            raise serializers.ValidationError("Path must start with '/'")

        if ".." in normalized:
            raise serializers.ValidationError("Path traversal not allowed")

        is_allowed = normalized in ALLOWED_VERCEL_PATHS or any(
            normalized.startswith(prefix) for prefix in ALLOWED_VERCEL_PATH_PREFIXES
        )
        if not is_allowed:
            raise serializers.ValidationError(
                f"Path '{normalized}' is not in the allowlist of permitted Vercel API paths"
            )

        return normalized


def _extract_access_token(integration: OrganizationIntegration) -> str:
    token = integration.config.get("credentials", {}).get("access_token")
    if not token:
        raise ValueError(f"No access token found for integration {integration.integration_id}")
    return token


def forward_to_vercel(config_id: str, access_token: str, path: str, method: str, body: dict) -> requests.Response:
    url = f"{VERCEL_API_BASE_URL}/v1/installations/{config_id}{path}"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    return requests.request(
        method=method,
        url=url,
        headers=headers,
        json=body if body else None,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )


class VercelProxyViewSet(viewsets.ViewSet):
    """
    Proxy endpoint for the billing service to call Vercel APIs.

    The billing service sends requests here with the Vercel API path and body.
    PostHog validates the JWT, looks up the Vercel token from OrganizationIntegration,
    and forwards the request to Vercel.

    """

    authentication_classes = [BillingServiceAuthentication]
    permission_classes = [AllowAny]

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = VercelProxyRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        path = serializer.validated_data["path"]
        method = serializer.validated_data["method"]
        body = serializer.validated_data.get("body", {})

        user = cast(BillingServiceUser, request.user)
        organization_id = user.organization_id

        integration = self._get_integration(organization_id)
        if not integration:
            return Response(
                {"error": "No Vercel integration found for this organization"},
                status=status.HTTP_404_NOT_FOUND,
            )

        access_token = self._get_access_token(integration, organization_id)
        if not access_token:
            return Response(
                {"error": "Failed to retrieve Vercel credentials"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return self._call_vercel(integration.integration_id, access_token, path, method, body)

    def _get_integration(self, organization_id: str) -> OrganizationIntegration | None:
        try:
            integration = OrganizationIntegration.objects.get(
                organization_id=organization_id,
                kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            )
            if not integration.integration_id:
                capture_exception(
                    ValueError("Vercel integration missing integration_id"),
                    {"organization_id": organization_id},
                )
                logger.error("Vercel integration missing integration_id", organization_id=organization_id)
                return None
            return integration
        except OrganizationIntegration.DoesNotExist:
            capture_exception(
                ValueError("Vercel integration not found"),
                {"organization_id": organization_id},
            )
            logger.warning("Vercel integration not found", organization_id=organization_id)
            return None

    def _get_access_token(self, integration: OrganizationIntegration, organization_id: str) -> str | None:
        try:
            return _extract_access_token(integration)
        except ValueError as e:
            capture_exception(e, {"organization_id": organization_id, "config_id": integration.integration_id})
            logger.exception(
                "Failed to extract Vercel access token",
                organization_id=organization_id,
                config_id=integration.integration_id,
            )
            return None

    def _call_vercel(self, config_id: str | None, access_token: str, path: str, method: str, body: dict) -> Response:
        if not config_id:
            capture_exception(ValueError("Vercel integration has no config_id"), {"path": path, "method": method})
            logger.error("Vercel integration missing config_id")
            return Response(
                {"error": "Invalid Vercel integration configuration"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        logger.info("Vercel API proxy request", config_id=config_id, path=path, method=method)

        try:
            vercel_response = forward_to_vercel(
                config_id=config_id,
                access_token=access_token,
                path=path,
                method=method,
                body=body,
            )
        except requests.RequestException as e:
            capture_exception(e, {"config_id": config_id, "path": path, "method": method})
            logger.exception("Vercel API proxy request failed", config_id=config_id, path=path)
            return Response(
                {"error": "Failed to reach Vercel API"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        self._log_vercel_response(vercel_response, config_id, path)

        try:
            response_data = vercel_response.json()
        except requests.JSONDecodeError:
            response_data = {"raw_response": vercel_response.text}

        return Response(response_data, status=vercel_response.status_code)

    def _log_vercel_response(self, response: requests.Response, config_id: str, path: str) -> None:
        if response.ok:
            logger.info(
                "Vercel API proxy request succeeded",
                config_id=config_id,
                path=path,
                status_code=response.status_code,
            )
        else:
            capture_exception(
                ValueError("Vercel API request failed"),
                {"config_id": config_id, "path": path, "status_code": response.status_code},
            )
            logger.error(
                "Vercel API proxy request failed",
                config_id=config_id,
                path=path,
                status_code=response.status_code,
                response_text=response.text[:500],
            )
