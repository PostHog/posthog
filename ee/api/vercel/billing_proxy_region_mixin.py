import json
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse

import requests
import structlog
from rest_framework import exceptions, status
from rest_framework.request import Request

from posthog.exceptions_capture import capture_exception
from posthog.models.organization_integration import OrganizationIntegration

from ee.api.authentication import BillingServiceAuthentication

logger = structlog.get_logger(__name__)


class BillingProxyRegionMixin:
    """
    Mixin for handling region-based request routing for the billing proxy.

    If a Vercel integration doesn't exist in US, proxy the request to EU.
    This mirrors the pattern in VercelRegionProxyMixin but uses organization_id
    from the billing service JWT instead of installation_id from Vercel's JWT.
    """

    PROXY_TIMEOUT = 10
    US_DOMAIN = getattr(settings, "REGION_US_DOMAIN", "us.posthog.com")
    EU_DOMAIN = getattr(settings, "REGION_EU_DOMAIN", "eu.posthog.com")

    @property
    def is_dev_env(self) -> bool:
        return settings.SITE_URL.startswith("http://localhost") or settings.DEBUG

    @property
    def current_region(self) -> str | None:
        if settings.SITE_URL == f"https://{self.US_DOMAIN}":
            return "us"
        elif settings.SITE_URL == f"https://{self.EU_DOMAIN}":
            return "eu"
        return None

    def _has_local_integration(self, organization_id: str) -> bool:
        return OrganizationIntegration.objects.filter(
            organization_id=organization_id,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
        ).exists()

    def _should_proxy_to_eu(self, organization_id: str) -> bool:
        if self.current_region != "us":
            return False
        return not self._has_local_integration(organization_id)

    def _proxy_to_eu(self, request: HttpRequest) -> HttpResponse:
        target_url = f"https://{self.EU_DOMAIN}/api/vercel/proxy/"

        try:
            response = requests.post(
                url=target_url,
                headers={
                    "Authorization": request.headers.get("Authorization", ""),
                    "Content-Type": "application/json",
                },
                data=request.body,
                timeout=self.PROXY_TIMEOUT,
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

            return HttpResponse(
                content=json.dumps(data),
                status=response.status_code,
                content_type="application/json",
            )

        except requests.exceptions.RequestException as e:
            capture_exception(e)
            logger.exception(
                "Failed to proxy billing request to EU region",
                url=target_url,
                error=str(e),
            )
            return HttpResponse(
                content=json.dumps({"error": "Unable to proxy request to EU region"}),
                status=status.HTTP_502_BAD_GATEWAY,
                content_type="application/json",
            )

    def _extract_organization_id(self, request: HttpRequest) -> str | None:
        try:
            drf_request = Request(request)
            auth_result = BillingServiceAuthentication().authenticate(drf_request)
            return auth_result[0].organization_id if auth_result else None
        except exceptions.AuthenticationFailed:
            return None

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if self.is_dev_env or not self.current_region:
            return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]

        organization_id = self._extract_organization_id(request)

        if organization_id and self._should_proxy_to_eu(organization_id):
            logger.info(
                "Proxying billing request to EU region",
                organization_id=organization_id,
                current_region=self.current_region,
            )
            return self._proxy_to_eu(request)

        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]
