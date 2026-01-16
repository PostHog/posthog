import json

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt

import structlog
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.person import get_person_name
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import Team
from posthog.models.person.person import PersonDistinctId
from posthog.models.person.util import get_persons_by_distinct_ids
from posthog.utils import load_data_from_request
from posthog.utils_cors import cors_response

from products.workflows.backend.models.push_subscription import PushPlatform, PushSubscription

logger = structlog.get_logger(__name__)


class PushSubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PushSubscription
        fields = ["id", "distinct_id", "token", "platform", "is_active", "created_at", "updated_at"]
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

    @action(methods=["GET"], detail=False)
    def list(self, request: Request, *args, **kwargs) -> Response:
        """
        List push subscriptions with person identification data but without the secret token.
        Returns only id, distinct_id, platform, and person identification (email, name).
        Only returns active subscriptions.
        """
        queryset = self.safely_get_queryset(self.get_queryset())
        subscriptions = queryset.filter(is_active=True)

        distinct_ids = list(subscriptions.values_list("distinct_id", flat=True).distinct())

        if not distinct_ids:
            return Response({"results": []}, status=status.HTTP_200_OK)

        persons_qs = get_persons_by_distinct_ids(self.team_id, distinct_ids)
        persons = {p.id: p for p in persons_qs}

        person_distinct_ids = PersonDistinctId.objects.filter(team_id=self.team_id, distinct_id__in=distinct_ids)

        distinct_id_to_person = {}
        for pdi in person_distinct_ids:
            if pdi.distinct_id not in distinct_id_to_person and pdi.person_id in persons:
                distinct_id_to_person[pdi.distinct_id] = persons[pdi.person_id]

        team = Team.objects.get(pk=self.team_id)

        results = []
        for subscription in subscriptions:
            person = distinct_id_to_person.get(subscription.distinct_id)
            person_email = person.email if person else None
            person_name = get_person_name(team, person) if person else None

            results.append(
                {
                    "id": subscription.id,
                    "distinct_id": subscription.distinct_id,
                    "platform": subscription.platform,
                    "created_at": subscription.created_at,
                    "updated_at": subscription.updated_at,
                    "person_email": person_email,
                    "person_name": person_name,
                }
            )

        return Response({"results": results}, status=status.HTTP_200_OK)

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
        "platform": "android" | "ios" | "web"
    }
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

    if not subscription.is_active or subscription.disabled_reason:
        subscription.is_active = True
        subscription.disabled_reason = None
        subscription.save(update_fields=["is_active", "disabled_reason"])

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
