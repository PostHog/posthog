from urllib.parse import urlparse

from django.http import HttpResponse, HttpResponseRedirect

import structlog
from rest_framework import decorators, exceptions, permissions, serializers, viewsets
from rest_framework.request import Request

from posthog.utils_cors import KNOWN_ORIGINS

from ee.api.vercel.vercel_error_mixin import VercelErrorResponseMixin
from ee.vercel.integration import VercelIntegration

logger = structlog.get_logger(__name__)


class VercelSSORedirectSerializer(serializers.Serializer):
    mode = serializers.CharField(required=True)
    code = serializers.CharField(required=True)
    state = serializers.CharField(required=True)
    product_id = serializers.CharField(required=False, allow_blank=True)
    resource_id = serializers.CharField(required=False, allow_blank=True)
    project_id = serializers.CharField(required=False, allow_blank=True)
    experimentation_item_id = serializers.CharField(required=False, allow_blank=True)
    path = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Area to redirect to after SSO. Possible values: billing, usage, support",
    )
    url = serializers.CharField(
        required=False, allow_blank=True, help_text="Provider-specific URL to redirect user to after SSO"
    )

    def validate_mode(self, value: str) -> str:
        if value != "sso":
            raise serializers.ValidationError("Mode must be 'sso'")
        return value

    def validate_path(self, value: str | None) -> str | None:
        valid_paths = {"billing", "usage", "support"}
        if value and value not in valid_paths:
            raise serializers.ValidationError(f"Path must be one of: {', '.join(valid_paths)}")
        return value

    def validate_url(self, value: str | None) -> str | None:
        if not value:
            return value

        try:
            parsed = urlparse(value)

            if parsed.scheme not in {"http", "https"}:
                raise serializers.ValidationError("URL must use http or https scheme")

            netloc = parsed.hostname
            if not netloc or netloc not in KNOWN_ORIGINS:
                raise serializers.ValidationError("URL domain is not allowed")
            if netloc not in KNOWN_ORIGINS:
                raise serializers.ValidationError("URL domain is not allowed")

            return value
        except serializers.ValidationError:
            raise
        except Exception:
            logger.exception("Failed to validate URL", url=value)
            raise serializers.ValidationError("Invalid URL format")


class VercelSSOViewSet(VercelErrorResponseMixin, viewsets.GenericViewSet):
    permission_classes = [permissions.AllowAny]

    @decorators.action(detail=False, methods=["get"], url_path="redirect")
    def sso_redirect(self, request: Request) -> HttpResponse:
        """
        https://vercel.com/docs/integrations/create-integration/marketplace-api#vercel-initiated-sso
        """
        serializer = VercelSSORedirectSerializer(data=request.query_params)
        if not serializer.is_valid():
            logger.exception("Invalid Vercel SSO parameters", errors=serializer.errors, integration="vercel")
            raise exceptions.ValidationError("Invalid parameters")

        data = serializer.validated_data

        redirect_url = VercelIntegration.authenticate_sso(
            request=request._request,
            code=data["code"],
            state=data.get("state"),
            resource_id=data.get("resource_id"),
            path=data.get("path"),
            url=data.get("url"),
            experimentation_item_id=data.get("experimentation_item_id"),
        )

        return HttpResponseRedirect(redirect_url)
