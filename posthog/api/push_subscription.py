from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.push_subscription import PushPlatform, PushSubscription


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
