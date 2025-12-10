from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

import structlog
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import Team
from posthog.models.push_subscription import PushPlatform, PushSubscription
from posthog.utils import load_data_from_request
from posthog.utils_cors import cors_response

logger = structlog.get_logger(__name__)


class PushSubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PushSubscription
        fields = ["id", "distinct_id", "token", "platform", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


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
            "platform": "android" | "ios" | "web"
        }
        """
        distinct_id = request.data.get("distinct_id")
        token = request.data.get("token")
        platform = request.data.get("platform")

        if not distinct_id:
            return Response({"error": "distinct_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        if not token:
            return Response({"error": "token is required"}, status=status.HTTP_400_BAD_REQUEST)
        if not platform:
            return Response({"error": "platform is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            platform_enum = PushPlatform(platform)
        except ValueError:
            return Response(
                {"error": f"Invalid platform. Must be one of: {[p.value for p in PushPlatform]}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        subscription = PushSubscription.upsert_token(
            team_id=self.team_id,
            distinct_id=distinct_id,
            token=token,
            platform=platform_enum,
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

        count = PushSubscription.deactivate_token(team_id=self.team_id, token=token)

        return Response({"deactivated": count}, status=status.HTTP_200_OK)

    @action(methods=["GET"], detail=False)
    def lookup(self, request: Request, *args, **kwargs) -> Response:
        """
        Lookup push tokens for a distinct_id.

        Used internally by Hog functions to send push notifications.

        Query params:
            distinct_id: The user's distinct_id
            platform: (optional) Filter by platform (android, ios, web)
        """
        distinct_id = request.query_params.get("distinct_id")
        platform = request.query_params.get("platform")

        if not distinct_id:
            return Response({"error": "distinct_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        platform_enum = None
        if platform:
            try:
                platform_enum = PushPlatform(platform)
            except ValueError:
                return Response(
                    {"error": f"Invalid platform. Must be one of: {[p.value for p in PushPlatform]}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        subscriptions = PushSubscription.get_active_tokens_for_distinct_id(
            team_id=self.team_id,
            distinct_id=distinct_id,
            platform=platform_enum,
        )

        return Response(
            {"tokens": [{"token": sub.token, "platform": sub.platform} for sub in subscriptions]},
            status=status.HTTP_200_OK,
        )


@csrf_exempt
def sdk_push_subscription_register(request):
    """
    SDK endpoint for registering push notification tokens.

    This endpoint is called by mobile SDKs using the API key for authentication.
    URL: POST /sdk/push_subscriptions/register/

    Expected payload:
    {
        "api_key": "phc_xxx...",
        "distinct_id": "user-123",
        "token": "fcm-token-abc123...",
        "platform": "android" | "ios" | "web"
    }
    """
    if request.method == "OPTIONS":
        return cors_response(request, JsonResponse({"status": "ok"}))

    if request.method != "POST":
        return cors_response(request, JsonResponse({"error": "Method not allowed"}, status=405))

    try:
        data = load_data_from_request(request)
    except Exception as e:
        logger.warning("push_subscription_register_parse_error", error=str(e))
        return cors_response(request, JsonResponse({"error": "Invalid request body"}, status=400))

    api_key = data.get("api_key")
    if not api_key:
        return cors_response(request, JsonResponse({"error": "api_key is required"}, status=400))

    try:
        team = Team.objects.get(api_token=api_key)
    except Team.DoesNotExist:
        return cors_response(request, JsonResponse({"error": "Invalid API key"}, status=401))

    distinct_id = data.get("distinct_id")
    token = data.get("token")
    platform = data.get("platform")

    if not distinct_id:
        return cors_response(request, JsonResponse({"error": "distinct_id is required"}, status=400))
    if not token:
        return cors_response(request, JsonResponse({"error": "token is required"}, status=400))
    if not platform:
        return cors_response(request, JsonResponse({"error": "platform is required"}, status=400))

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

    subscription = PushSubscription.upsert_token(
        team_id=team.id,
        distinct_id=distinct_id,
        token=token,
        platform=platform_enum,
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


@csrf_exempt
def internal_push_subscription_lookup(request):
    """
    Internal endpoint for looking up push tokens by distinct_id.

    Used by Hog functions (Firebase Push destination) to send push notifications.
    URL: POST /api/internal/push_subscriptions/lookup/

    Expected payload:
    {
        "team_id": 1,
        "distinct_id": "user-123",
        "platform": "android" (optional)
    }

    Note: This is an internal API - only accessible from plugin-server.
    In production, this should be protected by internal networking.
    """
    if request.method == "OPTIONS":
        return JsonResponse({"status": "ok"})

    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        data = load_data_from_request(request)
    except Exception as e:
        logger.warning("push_subscription_lookup_parse_error", error=str(e))
        return JsonResponse({"error": "Invalid request body"}, status=400)

    team_id = data.get("team_id")
    distinct_id = data.get("distinct_id")
    platform = data.get("platform")

    if not team_id:
        return JsonResponse({"error": "team_id is required"}, status=400)
    if not distinct_id:
        return JsonResponse({"error": "distinct_id is required"}, status=400)

    platform_enum = None
    if platform:
        try:
            platform_enum = PushPlatform(platform)
        except ValueError:
            return JsonResponse(
                {"error": f"Invalid platform. Must be one of: {[p.value for p in PushPlatform]}"},
                status=400,
            )

    subscriptions = PushSubscription.get_active_tokens_for_distinct_id(
        team_id=team_id,
        distinct_id=distinct_id,
        platform=platform_enum,
    )

    return JsonResponse({"tokens": [{"token": sub.token, "platform": sub.platform} for sub in subscriptions]})
