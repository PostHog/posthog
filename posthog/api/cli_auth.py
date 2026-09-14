"""
CLI Authentication API using OAuth2 Device Flow

This implements the device authorization flow (RFC 8628) for the PostHog CLI.
Users can authenticate without copying/pasting API keys.

Flow:
1. CLI requests device code
2. User opens browser and authorizes
3. CLI polls for completion
4. Returns Personal API Key
"""

import string
import secrets
from datetime import timedelta

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from posthog.api.personal_api_key import validate_personal_api_key_scopes
from posthog.auth import SessionAuthentication
from posthog.models import PersonalAPIKey, Team, User
from posthog.models.cli_device_authorization import CLIDeviceAuthorization
from posthog.models.utils import generate_random_token_personal, hash_key_value, mask_key_value
from posthog.rate_limit import CLIDeviceCodeThrottle
from posthog.scopes import UNPRIVILEGED_SCOPES
from posthog.session.activity import request_session_is_live

# Device code lives for 10 minutes
DEVICE_CODE_EXPIRY_SECONDS = 600

# CLI polling interval (5 seconds)
CLI_POLL_INTERVAL_SECONDS = 5
MAX_EXPIRED_DEVICE_AUTHORIZATIONS_CLEANED = 1000

# Scopes granted to CLI
CLI_SCOPES = [
    "event_definition:read",
    "property_definition:read",
    "error_tracking:write",
]

logger = structlog.get_logger(__name__)


def generate_user_code() -> str:
    """Generate a human-readable code like 'ABCD-1234'"""
    letters = "".join(secrets.choice(string.ascii_uppercase) for _ in range(4))
    numbers = "".join(secrets.choice(string.digits) for _ in range(4))
    return f"{letters}-{numbers}"


def generate_device_code() -> str:
    """Generate a secure random device code"""
    return secrets.token_urlsafe(32)


def get_device_cache_key(device_code: str) -> str:
    """Get cache key for device code"""
    return f"cli_device:{device_code}"


def get_user_code_cache_key(user_code: str) -> str:
    """Get cache key for user code"""
    return f"cli_user_code:{user_code}"


def get_validation_error_description(error: serializers.ValidationError) -> str:
    detail = error.detail
    if isinstance(detail, list) and detail:
        return str(detail[0])
    return str(detail)


def _cache_set(key: str, value: object, timeout: int) -> None:
    try:
        cache.set(key, value, timeout=timeout)
    except Exception:
        logger.warning("cli_device_authorization_cache_write_failed")


class DeviceCodeResponseSerializer(serializers.Serializer):
    """Response containing device and user codes"""

    device_code = serializers.CharField(help_text="Code for CLI to poll with")
    user_code = serializers.CharField(help_text="Code for user to enter in browser")
    verification_uri = serializers.CharField(help_text="URL for user to visit")
    verification_uri_complete = serializers.CharField(help_text="URL with code pre-filled")
    expires_in = serializers.IntegerField(help_text="Seconds until code expires")
    interval = serializers.IntegerField(help_text="Polling interval in seconds")


class DeviceAuthorizationSerializer(serializers.Serializer):
    """User authorizes the device code"""

    user_code = serializers.CharField(max_length=9, help_text="The user code displayed in CLI")
    project_id = serializers.IntegerField(help_text="The project to authorize CLI access for")
    scopes = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Scopes to grant to the CLI (defaults to CLI_SCOPES)",
    )


class DevicePollSerializer(serializers.Serializer):
    """CLI polls for authorization status"""

    device_code = serializers.CharField(help_text="Device code from initial request")


class DevicePollResponseSerializer(serializers.Serializer):
    """Response to poll request"""

    status = serializers.ChoiceField(choices=["pending", "authorized", "expired"])
    personal_api_key = serializers.CharField(required=False, help_text="The API key (only if authorized)")
    label = serializers.CharField(required=False, help_text="Label of the created key")  # type: ignore[assignment]
    project_id = serializers.CharField(required=False, help_text="The project ID (only if authorized)")
    scopes = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Scopes granted to the created API key (only if authorized)",
    )


@extend_schema(extensions={"x-product": "core"})
class CLIAuthViewSet(viewsets.ViewSet):
    """
    OAuth2 Device Authorization Flow for CLI authentication

    Endpoints:
    - POST /api/cli-auth/device-code/  (no auth required)
    - POST /api/cli-auth/authorize/    (session auth required)
    - POST /api/cli-auth/poll/         (no auth required)
    """

    def get_permissions(self):
        """Authorize endpoint requires auth, others don't"""
        if getattr(self, "action", None) == "authorize":
            return [IsAuthenticated()]
        return [AllowAny()]

    def get_authenticators(self):
        """Only use session auth for browser-based authorization"""
        action = getattr(self, "action", None)

        # Check both action and URL path since action might not be set yet
        if action == "authorize" or (hasattr(self, "request") and "authorize" in self.request.path):
            return [SessionAuthentication()]

        return []

    @extend_schema(request=None, responses={200: DeviceCodeResponseSerializer})
    @action(
        methods=["POST"],
        detail=False,
        url_path="device-code",
        throttle_classes=[CLIDeviceCodeThrottle],
    )
    def device_code(self, request):
        """
        Step 1: CLI requests device code

        Returns device code for polling and user code for browser authorization.
        """
        device_code = generate_device_code()
        user_code = generate_user_code()

        now = timezone.now()
        expired_ids = list(
            CLIDeviceAuthorization.objects.filter(expires_at__lt=now)
            .order_by("expires_at")
            .values_list("id", flat=True)[:MAX_EXPIRED_DEVICE_AUTHORIZATIONS_CLEANED]
        )
        if expired_ids:
            CLIDeviceAuthorization.objects.filter(id__in=expired_ids).delete()

        expires_at = now + timedelta(seconds=DEVICE_CODE_EXPIRY_SECONDS)
        CLIDeviceAuthorization.objects.create(
            device_code=device_code,
            user_code=user_code,
            expires_at=expires_at,
        )

        # Keep the cache as a fast path. The database row remains authoritative if either write fails.
        device_cache_key = get_device_cache_key(device_code)
        _cache_set(
            device_cache_key,
            {
                "user_code": user_code,
                "status": "pending",
                "created_at": timezone.now().isoformat(),
            },
            timeout=DEVICE_CODE_EXPIRY_SECONDS,
        )

        user_code_cache_key = get_user_code_cache_key(user_code)
        _cache_set(user_code_cache_key, device_code, timeout=DEVICE_CODE_EXPIRY_SECONDS)

        # Get the base URL for verification
        # In production this would be the actual domain
        base_url = request.build_absolute_uri("/").rstrip("/")

        response_data = {
            "device_code": device_code,
            "user_code": user_code,
            "verification_uri": f"{base_url}/cli/authorize",
            "verification_uri_complete": f"{base_url}/cli/authorize?code={user_code}",
            "expires_in": DEVICE_CODE_EXPIRY_SECONDS,
            "interval": CLI_POLL_INTERVAL_SECONDS,
        }

        serializer = DeviceCodeResponseSerializer(response_data)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(request=DeviceAuthorizationSerializer)
    @action(methods=["POST"], detail=False, url_path="authorize")
    def authorize(self, request):
        """
        Step 2: User authorizes in browser

        Requires authenticated session. Creates a Personal API Key and marks
        the device code as authorized.
        """
        serializer = DeviceAuthorizationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user_code = serializer.validated_data["user_code"]
        project_id = serializer.validated_data["project_id"]
        scopes = serializer.validated_data.get("scopes", CLI_SCOPES)
        user: User = request.user

        # Validate that at least one scope is provided
        if not scopes:
            return Response(
                {"error": "invalid_request", "error_description": "At least one scope is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            validate_personal_api_key_scopes(scopes, user, allowed_scopes=UNPRIVILEGED_SCOPES)
        except serializers.ValidationError as error:
            return Response(
                {"error": "invalid_scope", "error_description": get_validation_error_description(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            authorization = CLIDeviceAuthorization.objects.get(user_code=user_code)
        except CLIDeviceAuthorization.DoesNotExist:
            return Response(
                {"error": "invalid_code", "error_description": "User code not found or expired"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if authorization.expires_at <= timezone.now():
            return Response(
                {"error": "invalid_code", "error_description": "User code not found or expired"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if authorization.status != CLIDeviceAuthorization.Status.PENDING:
            return Response(
                {"error": "already_authorized", "error_description": "This code has already been authorized"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            team = Team.objects.get(id=project_id)
            if not user.organization_memberships.filter(organization=team.organization).exists():
                return Response(
                    {"error": "access_denied", "error_description": "You do not have access to this project"},
                    status=status.HTTP_403_FORBIDDEN,
                )
        except Team.DoesNotExist:
            return Response(
                {"error": "invalid_project", "error_description": "Project not found"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            authorization = CLIDeviceAuthorization.objects.select_for_update().get(pk=authorization.pk)
            if authorization.expires_at <= timezone.now():
                return Response(
                    {"error": "invalid_code", "error_description": "User code not found or expired"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if authorization.status != CLIDeviceAuthorization.Status.PENDING:
                return Response(
                    {"error": "already_authorized", "error_description": "This code has already been authorized"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            user = User.objects.select_for_update().get(pk=user.pk)
            if not request_session_is_live(request, user):
                return Response(
                    {"error": "session_revoked", "error_description": "Your session ended. Start the CLI login again."},
                    status=status.HTTP_403_FORBIDDEN,
                )

            api_key_value = generate_random_token_personal()
            mask_value = mask_key_value(api_key_value)
            secure_value = hash_key_value(api_key_value)
            timestamp = timezone.now().strftime("%Y-%m-%d %H:%M")
            max_team_name_len = 40 - len("CLI - ") - len(f" - {timestamp}")
            team_name_truncated = team.name[:max_team_name_len] if len(team.name) > max_team_name_len else team.name
            label = f"CLI - {team_name_truncated} - {timestamp}"
            had_prior_pat = PersonalAPIKey.objects.filter(user=user).exists()

            PersonalAPIKey.objects.create(
                user=user,
                label=label,
                secure_value=secure_value,
                mask_value=mask_value,
                scopes=scopes,
                scoped_teams=[team.id],
                scoped_organizations=[],
            )

            # A user-authorized CLI key does not need a review prompt when it is the user's first key.
            # Existing keys may come from a partner and still need review.
            if not had_prior_pat and user.credentials_reviewed_at is None:
                user.credentials_reviewed_at = timezone.now()
                user.save(update_fields=["credentials_reviewed_at"])

            authorization.status = CLIDeviceAuthorization.Status.AUTHORIZED
            authorization.user_id = user.id
            authorization.team_id = team.id
            authorization.scopes = scopes
            authorization.label = label
            authorization.personal_api_key_value = api_key_value
            authorization.authorized_at = timezone.now()
            authorization.save(
                update_fields=[
                    "status",
                    "user_id",
                    "team_id",
                    "scopes",
                    "label",
                    "personal_api_key_value",
                    "authorized_at",
                ]
            )

            device_data = {
                "user_code": user_code,
                "status": "authorized",
                "personal_api_key": api_key_value,
                "label": label,
                "project_id": str(team.id),
                "scopes": scopes,
                "authorized_at": authorization.authorized_at.isoformat(),
                "user_id": user.id,
            }

        _cache_set(get_device_cache_key(authorization.device_code), device_data, timeout=60)

        return Response(
            {
                "status": "success",
                "label": label,
                "mask_value": mask_value,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(request=DevicePollSerializer, responses={200: DevicePollResponseSerializer})
    @action(methods=["POST"], detail=False, url_path="poll")
    def poll(self, request):
        """
        Step 3: CLI polls for authorization status

        Returns:
        - 202: Still pending (keep polling)
        - 200: Authorized (includes API key)
        - 400: Expired or invalid
        """
        serializer = DevicePollSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        device_code = serializer.validated_data["device_code"]

        try:
            authorization = CLIDeviceAuthorization.objects.get(device_code=device_code)
        except CLIDeviceAuthorization.DoesNotExist:
            return Response(
                {"status": "expired", "error": "expired_token", "error_description": "Device code expired"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if authorization.expires_at <= timezone.now():
            return Response(
                {"status": "expired", "error": "expired_token", "error_description": "Device code expired"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if authorization.status == CLIDeviceAuthorization.Status.PENDING:
            return Response({"status": "pending"}, status=status.HTTP_202_ACCEPTED)

        if authorization.status == CLIDeviceAuthorization.Status.AUTHORIZED:
            with transaction.atomic():
                authorization = CLIDeviceAuthorization.objects.select_for_update().get(pk=authorization.pk)
                if authorization.status != CLIDeviceAuthorization.Status.AUTHORIZED:
                    return Response(
                        {"status": "expired", "error": "expired_token", "error_description": "Device code expired"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                api_key_value = authorization.personal_api_key_value
                if not api_key_value:
                    return Response(
                        {"status": "expired", "error": "expired_token", "error_description": "Device code expired"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                authorization.status = CLIDeviceAuthorization.Status.CONSUMED
                authorization.save(update_fields=["status"])

            response_data = {
                "status": "authorized",
                "personal_api_key": api_key_value,
                "label": authorization.label,
                "project_id": str(authorization.team_id),
                "scopes": authorization.scopes,
            }
            cache.delete(get_device_cache_key(device_code))
            cache.delete(get_user_code_cache_key(authorization.user_code))
            response_serializer = DevicePollResponseSerializer(response_data)
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        if authorization.status == CLIDeviceAuthorization.Status.CONSUMED:
            return Response(
                {"status": "expired", "error": "expired_token", "error_description": "Device code expired"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {"error": "invalid_request", "error_description": "Invalid device code status"},
            status=status.HTTP_400_BAD_REQUEST,
        )
