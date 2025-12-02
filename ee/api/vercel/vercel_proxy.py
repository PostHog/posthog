import urllib.parse
from typing import Any, cast

from django.conf import settings

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
        "/billing/invoices",
        "/billing/usage",
    ]
)

VERCEL_API_BASE_URL = "https://api.vercel.com"
REQUEST_TIMEOUT_SECONDS = 30
REGION_PROXY_TIMEOUT_SECONDS = 10
US_DOMAIN = getattr(settings, "REGION_US_DOMAIN", "us.posthog.com")
EU_DOMAIN = getattr(settings, "REGION_EU_DOMAIN", "eu.posthog.com")


class VercelProxyRequestSerializer(serializers.Serializer):
    path = serializers.CharField(help_text="The Vercel API path to call (e.g., '/billing/invoices')")
    method = serializers.ChoiceField(
        choices=["GET", "POST", "PUT", "PATCH", "DELETE"],
        help_text="HTTP method to use",
    )
    body = serializers.JSONField(required=False, default=dict, help_text="Request body to send to Vercel")

    def validate_path(self, value: str) -> str:
        # Normalize URL-encoded characters to prevent bypass
        normalized = urllib.parse.unquote(value)

        if not normalized.startswith("/"):
            raise serializers.ValidationError("Path must start with '/'")

        if ".." in normalized:
            raise serializers.ValidationError("Path traversal not allowed")

        if normalized not in ALLOWED_VERCEL_PATHS:
            raise serializers.ValidationError(
                f"Path '{normalized}' is not in the allowlist of permitted Vercel API paths"
            )

        return normalized


def _extract_access_token(integration: OrganizationIntegration) -> str:
    """Extract Vercel access token from integration config."""
    token = integration.config.get("credentials", {}).get("access_token")
    if not token:
        raise ValueError(f"No access token found for integration {integration.integration_id}")
    return token


def _get_current_region() -> str | None:
    """Determine which region this PostHog instance is running in."""
    site_url = getattr(settings, "SITE_URL", "")
    if site_url == f"https://{US_DOMAIN}":
        return "us"
    elif site_url == f"https://{EU_DOMAIN}":
        return "eu"
    return None


def _is_dev_env() -> bool:
    """Check if running in development environment."""
    site_url = getattr(settings, "SITE_URL", "")
    return site_url.startswith("http://localhost") or getattr(settings, "DEBUG", False)


def _proxy_to_eu(request_data: dict, auth_header: str) -> Response:
    """Proxy the request to EU PostHog instance."""
    target_url = f"https://{EU_DOMAIN}/api/vercel/proxy"

    try:
        response = requests.post(
            url=target_url,
            headers={
                "Authorization": auth_header,
                "Content-Type": "application/json",
            },
            json=request_data,
            timeout=REGION_PROXY_TIMEOUT_SECONDS,
        )

        logger.info(
            "Proxied billing request to EU region",
            target_url=target_url,
            status_code=response.status_code,
        )

        try:
            data = response.json() if response.content else {}
        except ValueError:
            data = {"error": "Invalid response from EU region"}

        return Response(data=data, status=response.status_code)

    except requests.exceptions.RequestException as e:
        capture_exception(e)
        logger.exception(
            "Failed to proxy billing request to EU region",
            url=target_url,
            error=str(e),
        )
        return Response(
            {"error": "Unable to proxy request to EU region"},
            status=status.HTTP_502_BAD_GATEWAY,
        )


def forward_to_vercel(config_id: str, access_token: str, path: str, method: str, body: dict) -> requests.Response:
    """Forward request to Vercel API."""
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

        user = cast(BillingServiceUser, request.user)
        organization_id = user.organization_id

        try:
            integration = OrganizationIntegration.objects.get(
                organization_id=organization_id,
                kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            )
        except OrganizationIntegration.DoesNotExist:
            current_region = _get_current_region()

            # If we're in US and integration not found, proxy to EU
            if current_region == "us" and not _is_dev_env():
                logger.info(
                    "Vercel integration not found in US, proxying to EU",
                    organization_id=organization_id,
                )
                auth_header = request.headers.get("Authorization", "")
                return _proxy_to_eu(request.data, auth_header)

            # If we're in EU (or dev) and not found, return 404
            logger.warning(
                "Vercel integration not found for organization",
                organization_id=organization_id,
                current_region=current_region,
            )
            return Response(
                {"error": "No Vercel integration found for this organization"},
                status=status.HTTP_404_NOT_FOUND,
            )

        config_id = integration.integration_id
        if not config_id:
            logger.error(
                "Vercel integration missing integration_id",
                organization_id=organization_id,
            )
            return Response(
                {"error": "Invalid Vercel integration configuration"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        try:
            access_token = _extract_access_token(integration)
        except ValueError as e:
            capture_exception(e)
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
        except requests.RequestException as e:
            capture_exception(e)
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
