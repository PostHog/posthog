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

from django.core.cache import cache
from django.utils import timezone

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from posthog.auth import SessionAuthentication
from posthog.models import PersonalAPIKey, User
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal, mask_key_value


class CLIAuthSessionAuthentication(SessionAuthentication):
    """
    Custom session authentication for CLI authorization.

    The user_code serves as an additional authorization token beyond CSRF,
    so we can safely skip CSRF validation for this specific endpoint.
    """

    def authenticate(self, request):
        """Authenticate using session authentication."""
        return super().authenticate(request)

    def enforce_csrf(self, request):
        """Skip CSRF enforcement - the user_code acts as the authorization token."""
        return None


# Device code lives for 10 minutes
DEVICE_CODE_EXPIRY_SECONDS = 600

# CLI polling interval (5 seconds)
CLI_POLL_INTERVAL_SECONDS = 5

# Scopes granted to CLI
CLI_SCOPES = [
    "event_definition:read",
    "property_definition:read",
    "error_tracking:write",
]


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


class DeviceCodeRequestSerializer(serializers.Serializer):
    """Request to initiate device authorization flow"""

    pass  # No input required


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
            return [CLIAuthSessionAuthentication()]

        return []

    @action(methods=["POST"], detail=False, url_path="device-code")
    def device_code(self, request):
        """
        Step 1: CLI requests device code

        Returns device code for polling and user code for browser authorization.
        """
        device_code = generate_device_code()
        user_code = generate_user_code()

        # Store in cache with expiry
        device_cache_key = get_device_cache_key(device_code)
        cache.set(
            device_cache_key,
            {
                "user_code": user_code,
                "status": "pending",
                "created_at": timezone.now().isoformat(),
            },
            timeout=DEVICE_CODE_EXPIRY_SECONDS,
        )

        # Also create reverse lookup (user_code -> device_code) for authorization
        user_code_cache_key = get_user_code_cache_key(user_code)
        cache.set(user_code_cache_key, device_code, timeout=DEVICE_CODE_EXPIRY_SECONDS)

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

    @action(methods=["POST"], detail=False, url_path="authorize")
    def authorize(self, request):
        """
        Step 2: User authorizes in browser

        Requires authenticated session. Creates a Personal API Key and marks
        the device code as authorized.

        The user_code itself acts as a single-use authorization token,
        providing additional security beyond CSRF tokens.
        """
        serializer = DeviceAuthorizationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user_code = serializer.validated_data["user_code"]
        project_id = serializer.validated_data["project_id"]
        scopes = serializer.validated_data.get("scopes", CLI_SCOPES)

        # Validate that at least one scope is provided
        if not scopes or len(scopes) == 0:
            return Response(
                {"error": "invalid_request", "error_description": "At least one scope is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Look up device code from user code
        user_code_cache_key = get_user_code_cache_key(user_code)
        device_code = cache.get(user_code_cache_key)
        if not device_code:
            return Response(
                {"error": "invalid_code", "error_description": "User code not found or expired"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get device code data
        device_cache_key = get_device_cache_key(device_code)
        device_data = cache.get(device_cache_key)
        if not device_data:
            return Response(
                {"error": "expired", "error_description": "Device code expired"}, status=status.HTTP_400_BAD_REQUEST
            )

        # Prevent duplicate authorization (race condition)
        if device_data.get("status") == "authorized":
            return Response(
                {"error": "already_authorized", "error_description": "This code has already been authorized"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Verify user has access to the project
        user: User = request.user
        from posthog.models import Team

        try:
            team = Team.objects.get(id=project_id)
            # Check if user has access to this team's organization
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

        # Create Personal API Key for the CLI
        api_key_value = generate_random_token_personal()
        mask_value = mask_key_value(api_key_value)
        secure_value = hash_key_value(api_key_value)

        # Label max length is 40 chars, so truncate if needed
        timestamp = timezone.now().strftime("%Y-%m-%d %H:%M")
        max_team_name_len = 40 - len("CLI - ") - len(f" - {timestamp}")
        team_name_truncated = team.name[:max_team_name_len] if len(team.name) > max_team_name_len else team.name
        label = f"CLI - {team_name_truncated} - {timestamp}"

        PersonalAPIKey.objects.create(
            user=user,
            label=label,
            secure_value=secure_value,
            mask_value=mask_value,
            scopes=scopes,
        )

        # Mark device as authorized and store the API key
        device_data["status"] = "authorized"
        device_data["personal_api_key"] = api_key_value
        device_data["label"] = label
        device_data["project_id"] = str(project_id)
        device_data["authorized_at"] = timezone.now().isoformat()
        device_data["user_id"] = user.id

        # Update cache with longer TTL to ensure CLI can poll
        cache.set(device_cache_key, device_data, timeout=60)  # 1 minute to retrieve

        return Response(
            {
                "status": "success",
                "label": label,
                "mask_value": mask_value,
            },
            status=status.HTTP_200_OK,
        )

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

        # Look up device code
        device_cache_key = get_device_cache_key(device_code)
        device_data = cache.get(device_cache_key)

        if not device_data:
            return Response(
                {"status": "expired", "error": "expired_token", "error_description": "Device code expired"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if device_data["status"] == "pending":
            # Still waiting for authorization
            return Response(
                {"status": "pending"},
                status=status.HTTP_202_ACCEPTED,  # Indicates to keep polling
            )

        if device_data["status"] == "authorized":
            # Success! Return the API key
            response_data = {
                "status": "authorized",
                "personal_api_key": device_data["personal_api_key"],
                "label": device_data["label"],
                "project_id": device_data["project_id"],
            }

            # Clean up - key has been retrieved
            cache.delete(device_cache_key)
            user_code_cache_key = get_user_code_cache_key(device_data["user_code"])
            cache.delete(user_code_cache_key)

            response_serializer = DevicePollResponseSerializer(response_data)
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        # Unknown status
        return Response(
            {"error": "invalid_request", "error_description": "Invalid device code status"},
            status=status.HTTP_400_BAD_REQUEST,
        )
