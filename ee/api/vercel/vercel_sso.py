from urllib.parse import urlparse

from django.http import HttpResponse, HttpResponseRedirect

import structlog
from rest_framework import decorators, exceptions, permissions, serializers, viewsets
from rest_framework.request import Request
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.utils_cors import KNOWN_ORIGINS

from ee.api.vercel.vercel_error_mixin import VercelErrorResponseMixin
from ee.vercel.integration import SSOParams, VercelIntegration

logger = structlog.get_logger(__name__)


class VercelSSOSerializer(DataclassSerializer[SSOParams]):
    class Meta:
        dataclass = SSOParams

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
        serializer = VercelSSOSerializer(data=request.query_params)
        if not serializer.is_valid():
            logger.exception("Invalid Vercel SSO parameters", errors=serializer.errors, integration="vercel")
            raise exceptions.ValidationError("Invalid parameters")

        redirect_url = VercelIntegration.authenticate_sso(request=request._request, params=serializer.validated_data)
        return HttpResponseRedirect(redirect_to=redirect_url)

    @decorators.action(detail=False, methods=["get"], url_path="continue")
    def sso_continue(self, request: Request) -> HttpResponse:
        # Require auth because this should only be called by users with an existing account
        # that needed to log in because they had an existing account with the email address in the SSO claims.
        if not request.user.is_authenticated:
            raise exceptions.NotAuthenticated("User must be logged in to continue SSO")

        serializer = VercelSSOSerializer(data=request.query_params)
        if not serializer.is_valid():
            raise exceptions.ValidationError("Invalid parameters")

        redirect_url = VercelIntegration.complete_sso_for_logged_in_user(
            request=request._request, params=serializer.validated_data
        )

        return HttpResponseRedirect(redirect_url)
