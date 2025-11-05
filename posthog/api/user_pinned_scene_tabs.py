from collections.abc import Iterable
from typing import Any, Optional, cast

from rest_framework import exceptions, serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.models import Team, User, UserPinnedSceneTabs
from posthog.permissions import APIScopePermission
from posthog.rate_limit import UserAuthenticationThrottle


class PinnedSceneTabSerializer(serializers.Serializer):
    id = serializers.CharField(required=False, allow_blank=True)
    pathname = serializers.CharField(required=False)
    search = serializers.CharField(required=False, allow_blank=True)
    hash = serializers.CharField(required=False, allow_blank=True)
    title = serializers.CharField(required=False, allow_blank=True)
    customTitle = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    iconType = serializers.CharField(required=False, allow_blank=True)
    sceneId = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    sceneKey = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    sceneParams = serializers.JSONField(required=False)
    pinned = serializers.BooleanField(required=False)


class PinnedSceneTabsSerializer(serializers.Serializer):
    tabs = PinnedSceneTabSerializer(many=True, required=False)
    personal_tabs = PinnedSceneTabSerializer(many=True, required=False)


class UserPinnedSceneTabsViewSet(viewsets.GenericViewSet):
    scope_object = "user"
    serializer_class = PinnedSceneTabsSerializer
    permission_classes = [IsAuthenticated, APIScopePermission]
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    throttle_classes = [UserAuthenticationThrottle]
    queryset = User.objects.filter(is_active=True)
    lookup_field = "uuid"

    def get_object(self) -> User:
        lookup_value = self.kwargs[self.lookup_field]
        request_user = cast(User, self.request.user)

        if lookup_value == "@me":
            self.check_object_permissions(self.request, request_user)
            return request_user

        if not request_user.is_staff:
            raise exceptions.PermissionDenied(
                "As a non-staff user you're only allowed to access the `@me` user instance."
            )

        return super().get_object()

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_staff:
            queryset = queryset.filter(id=self.request.user.id)
        return queryset

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        return self._get_response(instance)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        personal_tabs_payload = serializer.validated_data.get("personal_tabs")
        tabs_payload = serializer.validated_data.get("tabs")

        if personal_tabs_payload is None:
            personal_tabs_payload = tabs_payload or []

        team = instance.current_team
        if not team:
            raise serializers.ValidationError("Current team is required to manage pinned scene tabs.")

        pinned_tabs, legacy_project_tabs = self._get_pinned_tabs(instance, team)

        if personal_tabs_payload is not None:
            sanitized_tabs, _ = self._sanitize_tabs(personal_tabs_payload)
            pinned_tabs.tabs = sanitized_tabs
            pinned_tabs.save()

        if legacy_project_tabs:
            legacy_project_tabs.delete()

        return self._get_response(instance)

    def _get_response(self, instance: User) -> Response:
        team = instance.current_team
        if not team:
            raise serializers.ValidationError("Current team is required to manage pinned scene tabs.")

        pinned_tabs, legacy_project_tabs = self._get_pinned_tabs(instance, team)

        if legacy_project_tabs and legacy_project_tabs.tabs:
            if not pinned_tabs.tabs:
                sanitized_tabs, _ = self._sanitize_tabs(legacy_project_tabs.tabs)
                pinned_tabs.tabs = sanitized_tabs
                pinned_tabs.save()
            legacy_project_tabs.delete()

        personal_tabs_raw = pinned_tabs.tabs or []
        personal_tabs, changed = self._sanitize_tabs(personal_tabs_raw)
        if changed:
            pinned_tabs.tabs = personal_tabs
            pinned_tabs.save()

        return Response(
            {
                "tabs": personal_tabs,
                "personal_tabs": personal_tabs,
            }
        )

    def _sanitize_tabs(self, tabs: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
        sanitized_tabs: list[dict[str, Any]] = []
        changed = False
        for tab in tabs:
            sanitized = {**tab}
            if "active" in sanitized:
                sanitized.pop("active", None)
                changed = True
            if sanitized.get("pinned") is not True:
                sanitized["pinned"] = True
                changed = True
            sanitized_tabs.append(sanitized)
        return sanitized_tabs, changed

    def _get_pinned_tabs(self, instance: User, team: Team) -> tuple[UserPinnedSceneTabs, Optional[UserPinnedSceneTabs]]:
        pinned_tabs, _ = UserPinnedSceneTabs.objects.get_or_create(user=instance, team=team)
        legacy_project_tabs = UserPinnedSceneTabs.objects.filter(user=None, team=team).first()
        return pinned_tabs, legacy_project_tabs
