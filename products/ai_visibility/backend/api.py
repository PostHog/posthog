import re
import logging
from urllib.parse import urlparse

import requests
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.permissions import APIScopePermission

logger = logging.getLogger(__name__)


@extend_schema(tags=["ai-visibility"])
class DomainScraperViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """
    API for scraping domain information.
    """

    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "ai_visibility"

    @extend_schema(
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Domain URL to scrape"},
                },
                "required": ["domain"],
            }
        },
        responses={
            200: OpenApiResponse(
                response={
                    "type": "object",
                    "properties": {
                        "business_name": {"type": "string"},
                        "business_type": {"type": "string"},
                        "domain": {"type": "string"},
                    },
                },
                description="Scraped domain information",
            ),
            400: OpenApiResponse(description="Invalid domain"),
        },
        summary="Scrape domain",
        description="Scrape a domain and return basic business information",
    )
    @action(detail=False, methods=["post"], url_path="scrape")
    def scrape(self, request, *args, **kwargs):
        domain = request.data.get("domain")
        if not domain:
            return Response({"error": "Domain is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            parsed = urlparse(domain)
            if not parsed.scheme:
                domain = f"https://{domain}"

            logger.info(f"Scraping domain: {domain}")

            response = requests.get(domain, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()

            html = response.text

            title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
            business_name = title_match.group(1).strip() if title_match else "Unknown"

            description_match = re.search(
                r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']', html, re.IGNORECASE
            )
            description = description_match.group(1).strip() if description_match else ""

            business_type = "Unknown"
            if description:
                description_lower = description.lower()
                if any(word in description_lower for word in ["shop", "store", "buy", "product"]):
                    business_type = "E-commerce"
                elif any(word in description_lower for word in ["software", "saas", "platform", "app"]):
                    business_type = "Software/SaaS"
                elif any(word in description_lower for word in ["blog", "news", "article"]):
                    business_type = "Media/Blog"
                elif any(word in description_lower for word in ["service", "consulting", "agency"]):
                    business_type = "Service Provider"

            return Response(
                {
                    "business_name": business_name,
                    "business_type": business_type,
                    "domain": domain,
                }
            )

        except requests.exceptions.RequestException as e:
            logger.exception(f"Error scraping domain {domain}: {e}")
            return Response(
                {"error": f"Failed to scrape domain: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception as e:
            logger.exception(f"Unexpected error scraping domain {domain}: {e}")
            return Response({"error": "An unexpected error occurred"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
