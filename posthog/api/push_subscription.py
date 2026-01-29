import json

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt

import structlog
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import Team
from posthog.utils import load_data_from_request
from posthog.utils_cors import cors_response

from products.workflows.backend.models.push_subscription import PushPlatform, PushProvider, PushSubscription

logger = structlog.get_logger(__name__)


class PushSubscriptionSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        provider = attrs.get("provider", getattr(self.instance, "provider", None) if self.instance else None)
        firebase_app_id = attrs.get(
            "firebase_app_id", getattr(self.instance, "firebase_app_id", None) if self.instance else None
        )

        if provider == PushProvider.FCM and not firebase_app_id:
            raise serializers.ValidationError({"firebase_app_id": "firebase_app_id is required when provider is fcm"})

        return attrs

    class Meta:
        model = PushSubscription
        fields = [
            "id",
            "distinct_id",
            "token",
            "platform",
            "provider",
            "is_active",
            "created_at",
            "updated_at",
            "firebase_app_id",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
        extra_kwargs = {"token": {"write_only": True}}


class PushSubscriptionViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    API endpoint for managing push notification subscriptions.
    SDKs call this endpoint to register FCM tokens for push notifications.
    """

    scope_object = "INTERNAL"
    queryset = PushSubscription.objects.all()
    serializer_class = PushSubscriptionSerializer

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team_id)

    @action(methods=["POST"], detail=False)
    def register(self, request: Request, *args, **kwargs) -> Response:
        """
        Register a push notification token.
        Expected payload:
        {
            "distinct_id": "user-123",
            "token": "fcm-token-abc123...",
            "platform": "android" | "ios",
            "provider": "fcm" | "apns",
            "firebase_app_id": "app-id-123" (required if provider is fcm)
        }
        """
        distinct_id = request.data.get("distinct_id")
        token = request.data.get("token")
        platform = request.data.get("platform")
        provider = request.data.get("provider")
        firebase_app_id = request.data.get("firebase_app_id")

        if not distinct_id:
            return Response({"error": "distinct_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        if not token:
            return Response({"error": "token is required"}, status=status.HTTP_400_BAD_REQUEST)
        if not platform:
            return Response({"error": "platform is required"}, status=status.HTTP_400_BAD_REQUEST)
        if not provider:
            return Response({"error": "provider is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            platform_enum = PushPlatform(platform)
        except ValueError:
            return Response(
                {"error": f"Invalid platform. Must be one of: {[p.value for p in PushPlatform]}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            provider_enum = PushProvider(provider)
        except ValueError:
            return Response(
                {"error": f"Invalid provider. Must be one of: {[p.value for p in PushProvider]}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if provider_enum == PushProvider.FCM and not firebase_app_id:
            return Response(
                {"error": "firebase_app_id is required when provider is fcm"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        subscription = PushSubscription.upsert_token(
            team_id=self.team_id,
            distinct_id=distinct_id,
            token=token,
            platform=platform_enum,
            provider=provider_enum,
            firebase_app_id=firebase_app_id,
        )

        return Response(PushSubscriptionSerializer(subscription).data, status=status.HTTP_200_OK)

    @action(methods=["POST"], detail=False)
    def unregister(self, request: Request, *args, **kwargs) -> Response:
        """
        Unregister/deactivate a push notification token.
        Expected payload:
        {
            "token": "fcm-token-abc123..."
        }
        """
        token = request.data.get("token")

        if not token:
            return Response({"error": "token is required"}, status=status.HTTP_400_BAD_REQUEST)

        count = PushSubscription.deactivate_token(team_id=self.team_id, token=token, reason="unregistered")

        return Response({"deactivated": count}, status=status.HTTP_200_OK)


@csrf_exempt
def sdk_push_subscription_register(request: HttpRequest):
    """
    SDK endpoint for registering push notification tokens.
    This endpoint is called by mobile SDKs using the API key for authentication.
    URL: POST /api/sdk/push_subscriptions/register/
    Expected payload:
    {
        "api_key": "phc_xxx...",
        "distinct_id": "user-123",
        "token": "fcm-token-abc123...",
        "platform": "android" | "ios",
        "provider": "fcm" | "apns",
        "firebase_app_id": "app-id-123" (required if provider is fcm)
    }

    Security note: This endpoint uses @csrf_exempt because it's called by mobile SDKs
    that cannot provide CSRF tokens. Security is enforced via API key authentication
    (line 184), which validates the team's API key before processing the request.
    This is safe because:
    1. Only authenticated requests with valid API keys are processed
    2. The API key uniquely identifies the team, preventing cross-team access
    3. Mobile SDKs cannot obtain CSRF tokens, so CSRF protection would block legitimate requests
    """
    if request.method == "OPTIONS":
        return cors_response(request, JsonResponse({"status": "ok"}))

    if request.method != "POST":
        return cors_response(request, JsonResponse({"error": "Method not allowed"}, status=405))

    try:
        data = load_data_from_request(request)
        if isinstance(data, bytes):
            data = json.loads(data.decode("utf-8"))
        elif isinstance(data, str):
            data = json.loads(data)
    except Exception as e:
        logger.warning("push_subscription_register_parse_error", error=str(e))
        return cors_response(request, JsonResponse({"error": "Invalid request body"}, status=400))

    api_key = data.get("api_key")
    if not api_key:
        return cors_response(request, JsonResponse({"error": "api_key is required"}, status=400))

    team = Team.objects.get_team_from_token(api_key)
    if not team:
        return cors_response(request, JsonResponse({"error": "Invalid API key"}, status=401))

    distinct_id = data.get("distinct_id")
    token = data.get("token")
    platform = data.get("platform")
    provider = data.get("provider")
    firebase_app_id = data.get("firebase_app_id")

    if not distinct_id:
        return cors_response(request, JsonResponse({"error": "distinct_id is required"}, status=400))
    if not token:
        return cors_response(request, JsonResponse({"error": "token is required"}, status=400))
    if not platform:
        return cors_response(request, JsonResponse({"error": "platform is required"}, status=400))
    if not provider:
        return cors_response(request, JsonResponse({"error": "provider is required"}, status=400))

    try:
        platform_enum = PushPlatform(platform)
    except ValueError:
        return cors_response(
            request,
            JsonResponse(
                {"error": f"Invalid platform. Must be one of: {[p.value for p in PushPlatform]}"},
                status=400,
            ),
        )

    try:
        provider_enum = PushProvider(provider)
    except ValueError:
        return cors_response(
            request,
            JsonResponse(
                {"error": f"Invalid provider. Must be one of: {[p.value for p in PushProvider]}"},
                status=400,
            ),
        )

    if provider_enum == PushProvider.FCM and not firebase_app_id:
        return cors_response(
            request,
            JsonResponse({"error": "firebase_app_id is required when provider is fcm"}, status=400),
        )

    subscription = PushSubscription.upsert_token(
        team_id=team.id,
        distinct_id=distinct_id,
        token=token,
        platform=platform_enum,
        provider=provider_enum,
        firebase_app_id=firebase_app_id,
    )

    logger.info(
        "push_subscription_registered",
        team_id=team.id,
        distinct_id=distinct_id,
        platform=platform,
    )

    return cors_response(
        request,
        JsonResponse(
            {
                "status": "ok",
                "subscription_id": str(subscription.id),
            }
        ),
    )
