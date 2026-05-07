from collections.abc import Iterable
from typing import Any, Optional, cast

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import exceptions, serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.models import Team, User, UserHomeSettings
from posthog.permissions import APIScopePermission
from posthog.rate_limit import UserAuthenticationThrottle


class PinnedSceneTabSerializer(serializers.Serializer):
    id = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Stable identifier for the tab. Generated client-side; safe to omit on create.",
    )
    pathname = serializers.CharField(
        required=False,
        help_text=(
            "URL pathname the tab points at — for example `/project/123/dashboard/45` or `/project/123/insights`. "
            "Combined with `search` and `hash` to reconstruct the destination."
        ),
    )
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Query string portion of the URL, including the leading `?`. Empty string when there is no query.",
    )
    hash = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Fragment portion of the URL, including the leading `#`. Empty string when there is no fragment.",
    )
    title = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Default tab title derived from the destination scene. Used when `customTitle` is not set.",
    )
    customTitle = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Optional user-provided title that overrides `title` in the navigation UI.",
    )
    iconType = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Icon key shown next to the tab in the sidebar — for example `dashboard`, `insight`, `blank`.",
    )
    sceneId = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Scene identifier resolved from the pathname when known — used by the frontend for icon/title hints.",
    )
    sceneKey = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Scene key (logic key) for the destination, paired with `sceneParams` for deeper routing context.",
    )
    sceneParams = serializers.JSONField(
        required=False,
        help_text="Free-form scene parameters captured at pin time, used by the frontend to rehydrate the destination.",
    )
    pinned = serializers.BooleanField(
        required=False,
        help_text="Whether this entry is pinned. Always coerced to true on save — pass true or omit.",
    )


class PinnedSceneTabsSerializer(serializers.Serializer):
    tabs = PinnedSceneTabSerializer(
        many=True,
        required=False,
        help_text=(
            "Ordered list of pinned navigation tabs shown in the sidebar for the authenticated user within the "
            "current team. Send the full list to replace the existing pins; omit to leave them unchanged."
        ),
    )
    homepage = PinnedSceneTabSerializer(
        required=False,
        allow_null=True,
        help_text=(
            "Tab descriptor for the user's chosen home page — the destination opened when they click the PostHog "
            "logo or hit `/`. Set to a tab descriptor to pick a homepage, send `null` or `{}` to clear it and fall "
            "back to the project default."
        ),
    )


@extend_schema(tags=["platform_features"])
@extend_schema_view(
    retrieve=extend_schema(
        description=(
            "Get the authenticated user's pinned sidebar tabs and configured homepage for the current team. "
            "Pass `@me` as the UUID."
        ),
        responses={200: PinnedSceneTabsSerializer},
    ),
    partial_update=extend_schema(
        description=(
            "Update the authenticated user's pinned sidebar tabs and/or homepage for the current team. "
            "Pass `@me` as the UUID. Send `tabs` to replace the pinned tab list, `homepage` to set the home "
            "destination (any PostHog URL — dashboard, insight, search results, scene). Either field may be "
            "omitted to leave it unchanged; sending `homepage: null` or `{}` clears the homepage."
        ),
        request=PinnedSceneTabsSerializer,
        responses={200: PinnedSceneTabsSerializer},
    ),
)
class UserHomeSettingsViewSet(viewsets.GenericViewSet):
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

        tabs_specified = "tabs" in serializer.validated_data
        tabs_payload: Optional[Iterable[dict[str, Any]]]
        if tabs_specified:
            tabs_payload = serializer.validated_data.get("tabs") or []
        else:
            tabs_payload = None

        homepage_provided = "homepage" in serializer.validated_data
        homepage_payload = serializer.validated_data.get("homepage") if homepage_provided else None

        team = instance.current_team
        if not team:
            raise serializers.ValidationError("Current team is required to manage pinned scene tabs.")

        pinned_tabs = self._get_settings(instance, team)

        if tabs_payload is not None:
            sanitized_tabs, tabs_changed = self._sanitize_tabs(tabs_payload)
            if tabs_changed or sanitized_tabs != pinned_tabs.tabs:
                pinned_tabs.tabs = sanitized_tabs
                pinned_tabs.save()

        if homepage_provided:
            sanitized_homepage, homepage_changed = self._sanitize_tab(homepage_payload)
            if homepage_changed or sanitized_homepage != pinned_tabs.homepage:
                pinned_tabs.homepage = sanitized_homepage
                pinned_tabs.save()

        return self._get_response(instance)

    def _get_response(self, instance: User) -> Response:
        team = instance.current_team
        if not team:
            raise serializers.ValidationError("Current team is required to manage pinned scene tabs.")

        pinned_tabs = self._get_settings(instance, team)

        tabs_raw = pinned_tabs.tabs or []
        tabs, changed = self._sanitize_tabs(tabs_raw)
        if changed:
            pinned_tabs.tabs = tabs
            pinned_tabs.save()

        homepage, homepage_changed = self._sanitize_tab(pinned_tabs.homepage)
        if homepage_changed or homepage != pinned_tabs.homepage:
            pinned_tabs.homepage = homepage
            pinned_tabs.save()

        return Response(
            {
                "tabs": tabs,
                "homepage": homepage,
            }
        )

    def _sanitize_tabs(self, tabs: Iterable[Optional[dict[str, Any]]]) -> tuple[list[dict[str, Any]], bool]:
        sanitized_tabs: list[dict[str, Any]] = []
        changed = False
        for tab in tabs:
            sanitized, sanitized_changed = self._sanitize_tab(tab)
            if sanitized_changed:
                changed = True
            if sanitized is not None:
                sanitized_tabs.append(sanitized)
            elif tab is not None:
                changed = True
        return sanitized_tabs, changed

    def _sanitize_tab(self, tab: Optional[dict[str, Any]]) -> tuple[Optional[dict[str, Any]], bool]:
        if tab is None:
            return None, False

        if not tab:
            return None, False

        sanitized = {**tab}
        changed = False
        if "active" in sanitized:
            sanitized.pop("active", None)
            changed = True
        if sanitized.get("pinned") is not True:
            sanitized["pinned"] = True
            changed = True
        return sanitized, changed

    def _get_settings(self, instance: User, team: Team) -> UserHomeSettings:
        pinned_tabs, _ = UserHomeSettings.objects.get_or_create(user=instance, team=team)
        return pinned_tabs
