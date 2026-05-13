"""`/api/users/@me/push_tokens/` — register and unregister mobile push tokens.

The mobile app uploads its Expo push token after the user grants notification
permission. The backend fans out push notifications to every stored token
belonging to a user when something relevant happens (e.g. a PostHog Code task
run finishes or needs the user's input).
"""

from typing import cast

from django.utils import timezone as django_timezone

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.models.user import User
from posthog.models.user_push_token import UserPushToken
from posthog.permissions import APIScopePermission
from posthog.rate_limit import UserAuthenticationThrottle

logger = structlog.get_logger(__name__)


class UserPushTokenRegisterRequestSerializer(serializers.Serializer):
    token = serializers.CharField(
        max_length=512,
        help_text="Opaque push token issued by the device's platform push service (e.g. an Expo push token).",
    )
    platform = serializers.ChoiceField(
        choices=UserPushToken.Platform.choices,
        help_text="Device platform the token was issued for. One of `ios`, `android`, or `web`.",
    )


class UserPushTokenItemSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="PostHog UserPushToken row id.")
    platform = serializers.ChoiceField(
        choices=UserPushToken.Platform.choices,
        help_text="Device platform the token was issued for.",
    )
    created_at = serializers.DateTimeField(help_text="When this token was first registered.")
    last_seen_at = serializers.DateTimeField(help_text="Last time the mobile app re-registered this token.")


class UserPushTokenUnregisterRequestSerializer(serializers.Serializer):
    token = serializers.CharField(
        max_length=512,
        help_text="The opaque push token to remove for the authenticated user.",
    )


@extend_schema(tags=["core"])
class UserPushTokenViewSet(viewsets.GenericViewSet):
    """`/api/users/@me/push_tokens/` — manage the authenticated user's push notification tokens."""

    scope_object = "user"
    required_scopes: list[str] | None = None
    scope_object_read_actions: list[str] = []
    scope_object_write_actions = ["create", "unregister"]

    authentication_classes = [
        OAuthAccessTokenAuthentication,
        PersonalAPIKeyAuthentication,
        SessionAuthentication,
    ]
    permission_classes = [IsAuthenticated, APIScopePermission]
    throttle_classes = [UserAuthenticationThrottle]
    http_method_names = ["post"]
    serializer_class = UserPushTokenItemSerializer

    def _get_user(self) -> User:
        request_user = cast(User, self.request.user)
        uuid_param = self.kwargs.get("parent_lookup_uuid")
        if uuid_param is None or uuid_param == "@me":
            return request_user
        if not request_user.is_staff:
            raise exceptions.PermissionDenied(
                "As a non-staff user you're only allowed to access the `@me` user instance."
            )
        user = User.objects.filter(uuid=uuid_param, is_active=True).first()
        if user is None:
            raise exceptions.NotFound()
        return user

    @validated_request(
        request_serializer=UserPushTokenRegisterRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=UserPushTokenItemSerializer,
                description="Token was registered or refreshed.",
            ),
        },
        summary="Register a push notification token",
        description=(
            "Idempotent upsert: if the (user, token) pair already exists, `platform` and "
            "`last_seen_at` are refreshed. Otherwise a new row is created."
        ),
    )
    def create(self, request: Request, **_kwargs) -> Response:
        user = self._get_user()
        data = request.validated_data
        token: str = data["token"]
        platform: str = data["platform"]

        push_token, _created = UserPushToken.objects.update_or_create(
            user=user,
            token=token,
            defaults={"platform": platform, "last_seen_at": django_timezone.now()},
        )
        return Response(UserPushTokenItemSerializer(push_token).data)

    @validated_request(
        request_serializer=UserPushTokenUnregisterRequestSerializer,
        responses={204: OpenApiResponse(description="Token removed (or never existed).")},
        summary="Unregister a push notification token",
        description=(
            "Delete the row matching `(user, token)`. Returns 204 even if no row matches so "
            "the mobile client can call this unconditionally when the user opts out."
        ),
    )
    @action(methods=["POST"], detail=False, url_path="unregister")
    def unregister(self, request: Request, **_kwargs) -> Response:
        token = request.validated_data["token"]
        UserPushToken.objects.filter(user=self._get_user(), token=token).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
