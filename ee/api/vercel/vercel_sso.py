from dataclasses import asdict
from typing import Any
from urllib.parse import urlencode, urlparse

from django.http import HttpRequest, HttpResponse, HttpResponseRedirect

import structlog
from cryptography.fernet import InvalidToken
from rest_framework import decorators, exceptions, permissions, serializers, viewsets
from rest_framework.request import Request
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.exceptions_capture import capture_exception
from posthog.models.integration import Integration
from posthog.models.organization_integration import OrganizationIntegration
from posthog.utils_cors import KNOWN_ORIGINS

from ee.api.vercel.crypto import decrypt_payload, encrypt_payload, mark_token_used
from ee.api.vercel.types import VercelUserClaims
from ee.api.vercel.vercel_error_mixin import VercelErrorResponseMixin
from ee.api.vercel.vercel_region_proxy_mixin import VercelRegionProxyMixin
from ee.vercel.integration import SSOParams, VercelIntegration

SSO_CLAIMS_TOKEN_TTL = 300
SSO_SALT = "vercel_sso"

logger = structlog.get_logger(__name__)


class VercelSSOSerializer(DataclassSerializer[SSOParams]):
    class Meta:
        dataclass = SSOParams

    def validate_mode(self, value: str) -> str:
        if value != "sso":
            raise serializers.ValidationError("Mode must be 'sso'")
        return value

    def validate_path(self, value: str | None) -> str | None:
        valid_paths = {"billing", "usage", "support", "secrets", "onboarding"}
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


def _encrypt_claims(claims: Any) -> str:
    data = asdict(claims) if hasattr(claims, "__dataclass_fields__") else claims.__dict__
    return encrypt_payload(data, salt=SSO_SALT, jti=True)


def _decrypt_claims(token: str) -> dict:
    return decrypt_payload(token, salt=SSO_SALT, ttl=SSO_CLAIMS_TOKEN_TTL)


class VercelSSOViewSet(VercelErrorResponseMixin, VercelRegionProxyMixin, viewsets.GenericViewSet):
    permission_classes = [permissions.AllowAny]

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        # SSO codes are single-use, so we redirect the browser instead of proxying server-side
        return viewsets.GenericViewSet.dispatch(self, request, *args, **kwargs)  # type: ignore[return-value]  # ty: ignore[invalid-return-type]

    def _should_redirect_to_eu(self, resource_id: str | None, installation_id: str | None = None) -> bool:
        if self.is_dev_env or self.current_region != "us":
            return False
        if resource_id:
            try:
                resource_pk = int(resource_id)
            except (ValueError, TypeError):
                return False
            # nosemgrep: idor-lookup-without-team — intentionally cross-team: checking if resource exists anywhere in this region
            return not Integration.objects.filter(pk=resource_pk, kind=Integration.IntegrationKind.VERCEL).exists()
        if installation_id:
            return not OrganizationIntegration.objects.filter(
                kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
                integration_id=installation_id,
            ).exists()
        return False

    @decorators.action(detail=False, methods=["get"], url_path="redirect")
    def sso_redirect(self, request: Request) -> HttpResponse:
        """
        https://vercel.com/docs/integrations/create-integration/marketplace-api#vercel-initiated-sso
        """
        serializer = VercelSSOSerializer(data=request.query_params)
        if not serializer.is_valid():
            logger.exception("Invalid Vercel SSO parameters", errors=serializer.errors, integration="vercel")
            raise exceptions.ValidationError("Invalid parameters")

        params: SSOParams = serializer.validated_data

        if self._should_redirect_to_eu(params.resource_id):
            eu_url = f"https://{self.EU_DOMAIN}/login/vercel/?{request.query_params.urlencode()}"
            logger.info(
                "Redirecting SSO to EU region",
                resource_id=params.resource_id,
                integration="vercel",
            )
            return HttpResponseRedirect(redirect_to=eu_url)

        claims_token = request.query_params.get("_claims_token")
        if claims_token:
            try:
                claims_data = _decrypt_claims(claims_token)
                jti = claims_data.pop("jti", None)
                if jti and not mark_token_used(jti, ttl=SSO_CLAIMS_TOKEN_TTL):
                    logger.warning("Replay of cross-region SSO claims token", jti=jti, integration="vercel")
                else:
                    claims = VercelUserClaims(**claims_data)
                    VercelIntegration.set_cached_claims(params.code, claims, timeout=300)
                    logger.info(
                        "Restored SSO claims from cross-region token",
                        installation_id=claims.installation_id,
                        integration="vercel",
                    )
            except InvalidToken:
                logger.warning("Invalid or expired cross-region SSO claims token", integration="vercel")
            except Exception as e:
                capture_exception(e)
                logger.warning("Failed to decrypt cross-region SSO claims token", error=str(e), integration="vercel")

        if not params.resource_id and self.current_region == "us" and not self.is_dev_env:
            try:
                existing_claims = VercelIntegration._get_sso_claims_from_code(params.code, params.state)
            except Exception:
                existing_claims = None

            if isinstance(existing_claims, VercelUserClaims) and self._should_redirect_to_eu(
                None, installation_id=existing_claims.installation_id
            ):
                token = _encrypt_claims(existing_claims)
                eu_params = request.query_params.dict()
                eu_params["_claims_token"] = token
                eu_url = f"https://{self.EU_DOMAIN}/login/vercel/?{urlencode(eu_params)}"
                logger.info(
                    "Redirecting SSO to EU region after code exchange",
                    installation_id=existing_claims.installation_id,
                    integration="vercel",
                )
                return HttpResponseRedirect(redirect_to=eu_url)
            if isinstance(existing_claims, VercelUserClaims):
                VercelIntegration.set_cached_claims(params.code, existing_claims, timeout=300)

        redirect_url = VercelIntegration.authenticate_sso(request=request._request, params=params)
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
