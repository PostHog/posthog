import structlog
from django.conf import settings
from django.contrib.auth import login
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from rest_framework import permissions, serializers, status
from rest_framework.decorators import action
from rest_framework.viewsets import ViewSet

from ee.api.authentication import VercelAuthentication
from ee.models.vercel_installation import VercelInstallation
from ee.vercel.client import VercelAPIClient

logger = structlog.get_logger(__name__)


class VercelSSORedirectSerializer(serializers.Serializer):
    mode = serializers.CharField(required=True)
    code = serializers.CharField(required=True)
    state = serializers.CharField(required=False, allow_blank=True)

    def validate_mode(self, value):
        if value != "sso":
            raise serializers.ValidationError("Mode must be 'sso'")
        return value


class VercelSSOViewSet(ViewSet):
    permission_classes = (permissions.AllowAny,)

    @action(detail=False, methods=["get"], url_path="redirect")
    def sso_redirect(self, request: HttpRequest) -> HttpResponse:
        serializer = VercelSSORedirectSerializer(data=request.GET)
        if not serializer.is_valid():
            logger.error("vercel_sso_invalid_parameters", errors=serializer.errors)
            return JsonResponse({"error": "Invalid parameters"}, status=status.HTTP_400_BAD_REQUEST)

        code = serializer.validated_data["code"]
        state = serializer.validated_data.get("state")
        logger.info("vercel_sso_redirect_received", has_state=state is not None)

        client_id = getattr(settings, "VERCEL_CLIENT_ID", "")
        client_secret = getattr(settings, "VERCEL_CLIENT_SECRET", "")

        token_response = self._exchange_token(code, client_id, client_secret, state)
        if not token_response:
            return JsonResponse({"error": "Token exchange failed"}, status=status.HTTP_400_BAD_REQUEST)

        id_token = token_response.get("id_token")
        if not id_token:
            logger.error("vercel_sso_missing_id_token")
            return JsonResponse({"error": "Missing id_token"}, status=status.HTTP_400_BAD_REQUEST)

        jwt_payload = self._decode_jwt(id_token)
        if not jwt_payload:
            return JsonResponse({"error": "Invalid JWT token"}, status=status.HTTP_400_BAD_REQUEST)

        installation_id = jwt_payload.get("installation_id")
        if not installation_id:
            logger.error("vercel_sso_missing_installation_id")
            return JsonResponse({"error": "Missing installation_id"}, status=status.HTTP_400_BAD_REQUEST)

        user = self._find_user(installation_id)
        if not user:
            return JsonResponse({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        logger.info("vercel_sso_user_logged_in", user_id=user.id, installation_id=installation_id)
        return HttpResponseRedirect("/")

    def _exchange_token(self, code, client_id, client_secret, state):
        try:
            vercel_client = VercelAPIClient()
            return vercel_client.sso_token_exchange(
                code=code, client_id=client_id, client_secret=client_secret, state=state
            )
        except Exception:
            logger.exception("vercel_sso_token_exchange_error")
            return None

    def _decode_jwt(self, id_token):
        try:
            vercel_auth = VercelAuthentication()
            return vercel_auth._validate_jwt_token(id_token, "User")
        except Exception:
            logger.exception("vercel_sso_jwt_decode_error")
            return None

    def _find_user(self, installation_id):
        # TODO: This should be an email lookup based on the JWT payload, but we don't have that yet.
        try:
            vercel_installation = VercelInstallation.objects.get(installation_id=installation_id)
            return vercel_installation.organization.members.filter(is_active=True).first()
        except VercelInstallation.DoesNotExist:
            logger.exception("vercel_sso_installation_not_found", installation_id=installation_id)
            return None
