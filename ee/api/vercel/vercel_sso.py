import structlog
from django.conf import settings
from django.contrib.auth import login
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from rest_framework import permissions, serializers, status
from rest_framework.decorators import action
from rest_framework.viewsets import ViewSet

from ee.api.authentication import VercelAuthentication
from ee.api.vercel.vercel_installation import VercelErrorResponseMixin
from posthog.models.organization_integration import OrganizationIntegration
from posthog.models.integration import Integration
from ee.vercel.client import VercelAPIClient
from posthog.utils_cors import KNOWN_ORIGINS
from urllib.parse import urlparse

logger = structlog.get_logger(__name__)


class VercelSSORedirectSerializer(serializers.Serializer):
    mode = serializers.CharField(required=True)
    code = serializers.CharField(required=True)
    state = serializers.CharField(required=False, allow_blank=True)
    resource_id = serializers.CharField(required=False, allow_blank=True)
    product_id = serializers.CharField(required=False, allow_blank=True)
    project_id = serializers.CharField(required=False, allow_blank=True)
    experimentation_item_id = serializers.CharField(required=False, allow_blank=True)
    invoice_id = serializers.CharField(required=False, allow_blank=True)
    path = serializers.CharField(required=False, allow_blank=True)
    url = serializers.CharField(required=False, allow_blank=True)

    def validate_mode(self, value):
        if value != "sso":
            raise serializers.ValidationError("Mode must be 'sso'")
        return value

    def validate_path(self, value):
        if value and value not in ["billing", "usage", "support"]:
            raise serializers.ValidationError("Path must be one of: 'billing', 'usage', 'support'")
        return value

    def validate_url(self, value):
        if not value:
            return value

        try:
            parsed = urlparse(value)

            if parsed.scheme not in ["http", "https"]:
                raise serializers.ValidationError("URL must use http or https scheme")

            if parsed.netloc not in KNOWN_ORIGINS:
                raise serializers.ValidationError("URL domain is not in allowed origins")

            return value
        except serializers.ValidationError:
            raise
        except Exception:
            logger.exception("Failed to validate Vercel SSO URL", url=value)
            raise serializers.ValidationError("Invalid URL format")


class VercelSSOViewSet(VercelErrorResponseMixin, ViewSet):
    permission_classes = (permissions.AllowAny,)

    @action(detail=False, methods=["get"], url_path="redirect")
    def sso_redirect(self, request: HttpRequest) -> HttpResponse:
        serializer = VercelSSORedirectSerializer(data=request.GET)
        if not serializer.is_valid():
            logger.exception("Invalid parameters received for Vercel SSO redirect", errors=serializer.errors)
            return JsonResponse({"error": "Invalid parameters"}, status=status.HTTP_400_BAD_REQUEST)

        code = serializer.validated_data["code"]
        state = serializer.validated_data.get("state")
        resource_id = serializer.validated_data.get("resource_id")
        path = serializer.validated_data.get("path")
        url = serializer.validated_data.get("url")

        logger.info(
            "Received Vercel SSO redirect request",
            has_state=state is not None,
            has_resource_id=resource_id is not None,
            path=path,
            url=url,
        )

        client_id = settings.VERCEL_CLIENT_ID
        client_secret = settings.VERCEL_CLIENT_SECRET

        token_response = self._exchange_token(code, client_id, client_secret, state)
        if not token_response:
            return JsonResponse({"error": "Token exchange failed"}, status=status.HTTP_400_BAD_REQUEST)

        id_token = token_response.get("id_token")
        if not id_token:
            logger.exception("Missing id_token in Vercel SSO token response")
            return JsonResponse({"error": "Missing id_token"}, status=status.HTTP_400_BAD_REQUEST)

        jwt_payload = self._decode_jwt(id_token)
        if not jwt_payload:
            return JsonResponse({"error": "Invalid JWT token"}, status=status.HTTP_400_BAD_REQUEST)

        installation_id = jwt_payload.get("installation_id")
        if not installation_id:
            logger.exception("Missing installation_id in Vercel SSO JWT payload")
            return JsonResponse({"error": "Missing installation_id"}, status=status.HTTP_400_BAD_REQUEST)

        user = self._find_user(installation_id)
        if not user:
            return JsonResponse({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        login(request, user, backend="django.contrib.auth.backends.ModelBackend")

        if resource_id:
            self._set_active_project(user, resource_id)

        logger.info(
            "Successfully logged in user via Vercel SSO",
            user_id=user.id,
            installation_id=installation_id,
            resource_id=resource_id,
        )

        redirect_url = self._determine_redirect_url(path, url)
        return HttpResponseRedirect(redirect_url)

    def _exchange_token(self, code, client_id, client_secret, state):
        try:
            vercel_client = VercelAPIClient(bearer_token="dummy_token_for_sso")
            return vercel_client.sso_token_exchange(
                code=code, client_id=client_id, client_secret=client_secret, state=state
            )
        except Exception:
            logger.exception("Failed to exchange Vercel SSO token")
            return None

    def _decode_jwt(self, id_token):
        try:
            vercel_auth = VercelAuthentication()
            return vercel_auth._validate_jwt_token(id_token, "User")
        except Exception:
            logger.exception("Failed to decode Vercel SSO JWT token")
            return None

    def _find_user(self, installation_id):
        try:
            installation = OrganizationIntegration.objects.get(
                kind=Integration.IntegrationKind.VERCEL, integration_id=installation_id
            )
            return installation.organization.members.filter(is_active=True).first()
        except OrganizationIntegration.DoesNotExist:
            logger.exception("Vercel installation not found for SSO", installation_id=installation_id)
            return None

    def _set_active_project(self, user, resource_id):
        try:
            resource = Integration.objects.get(pk=resource_id)
            team = resource.team
            if team and user.teams.filter(pk=team.pk).exists():
                user.current_team = team
                user.save()
                logger.info(
                    "Successfully set active project for Vercel SSO user",
                    user_id=user.id,
                    team_id=team.id,
                    resource_id=resource_id,
                )
            else:
                logger.warning(
                    "User is not a member of the team for Vercel SSO resource",
                    user_id=user.id,
                    team_id=team.id if team else None,
                    resource_id=resource_id,
                )
        except Integration.DoesNotExist:
            logger.exception("Vercel SSO resource not found", resource_id=resource_id)

    def _determine_redirect_url(self, path, url):
        if url:
            return url

        if path == "billing":
            return "/organization/billing/overview"
        elif path == "usage":
            return "/organization/billing/usage"
        elif path == "support":
            return "/#panel=support"

        return "/"
