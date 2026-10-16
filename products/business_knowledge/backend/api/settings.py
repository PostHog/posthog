from functools import cached_property
from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User
from posthog.permissions import APIScopePermission, PostHogFeatureFlagPermission, get_authenticator_scoped_team_ids
from posthog.rate_limit import BurstRateThrottle, SustainedRateThrottle

from products.access_control.backend.facade.user_access_control import UserAccessControl

from .. import learning_settings
from .serializers import BusinessKnowledgeSettingsSerializer, BusinessKnowledgeSettingsUpdateSerializer


def canonical_user_access_control(view: TeamAndOrgViewSetMixin) -> UserAccessControl:
    """Access control for rows the parent project owns, so a child environment's own grant does not apply."""
    team = view.team.parent_team or view.team
    return UserAccessControl(user=cast(User, view.request.user), team=team, organization_id=view.organization_id)


class CanonicalTeamTokenPermission(BasePermission):
    """A child environment reaches parent-owned rows only when the caller can reach the parent project."""

    def has_permission(self, request: Request, view: Any) -> bool:
        canonical_id = view.team.parent_team_id or view.team.id
        authenticator = getattr(request, "successful_authenticator", None)
        scoped_teams = get_authenticator_scoped_team_ids(authenticator) if authenticator is not None else None
        if scoped_teams and canonical_id not in scoped_teams:
            self.message = f"API key does not have access to the requested project: ID {canonical_id}."
            return False
        # Core permissions check membership of the child only, and resource rules fall back to a default grant.
        if view.team.parent_team_id and not canonical_user_access_control(view).has_project_access:
            self.message = "You don't have access to the project."
            return False
        return True


class BusinessKnowledgeSettingsViewSet(TeamAndOrgViewSetMixin, ViewSet):
    scope_object = "business_knowledge"
    # Without this, AccessControlPermission falls through to has_any_specific_access_for_resource,
    # so editor access to one knowledge source would let a member whose resource-level access is
    # "none" read and flip this project-wide setting. Nothing catches it later: this is a plain
    # ViewSet with no queryset and no get_object, so has_object_permission never runs as a second
    # gate.
    requires_resource_level_access = True
    serializer_class = BusinessKnowledgeSettingsSerializer
    permission_classes = [
        IsAuthenticated,
        APIScopePermission,
        PostHogFeatureFlagPermission,
        CanonicalTeamTokenPermission,
    ]
    posthog_feature_flag = "product-business-knowledge"
    throttle_classes = [BurstRateThrottle, SustainedRateThrottle]
    pagination_class = None
    http_method_names = ["get", "patch", "head", "options"]

    @cached_property
    def user_access_control(self) -> UserAccessControl:
        # AccessControlPermission reads its resource-level check from here. Bind it to the
        # canonical team: the config row belongs to the parent project, so a child environment's
        # own `business_knowledge` grant must not read or change it when the parent grants `none`.
        return canonical_user_access_control(self)

    def dangerously_get_required_scopes(self, request: Request, view: Any) -> list[str] | None:
        # Combined GET+PATCH is neither list nor partial_update, so the default
        # scope mapping would 403 every personal API key. Split by method here.
        if self.action != "knowledge_settings":
            return None
        if request.method == "PATCH":
            return ["business_knowledge:write"]
        return ["business_knowledge:read"]

    def _serialize(self, *, learn_from_support_enabled: bool) -> dict[str, bool]:
        return BusinessKnowledgeSettingsSerializer(
            {
                "learn_from_support_enabled": learn_from_support_enabled,
                "support_enabled": bool(self.team.conversations_enabled),
            }
        ).data

    @extend_schema(
        methods=["GET"],
        request=None,
        responses={
            200: OpenApiResponse(
                response=BusinessKnowledgeSettingsSerializer,
                description="The team's Business knowledge learning settings.",
            ),
        },
        summary="Get business knowledge settings",
        description="Fetch whether this project learns from resolved support tickets, and whether Support is on in this environment.",
    )
    @extend_schema(
        methods=["PATCH"],
        request=BusinessKnowledgeSettingsUpdateSerializer,
        responses={
            200: OpenApiResponse(
                response=BusinessKnowledgeSettingsSerializer,
                description="The updated Business knowledge learning settings.",
            ),
            400: OpenApiResponse(description="Learn from support cannot be enabled while Support is off."),
        },
        summary="Update business knowledge settings",
        description="Partially update Business knowledge learning settings. Enabling learn-from-support requires Support to be on in this environment.",
    )
    @validated_request(
        request_serializer=BusinessKnowledgeSettingsUpdateSerializer,
        responses={200: OpenApiResponse(response=BusinessKnowledgeSettingsSerializer)},
        include_serializer_context=True,
    )
    # Not named `settings` — that would shadow DRF's `APIView.settings`.
    @action(detail=False, methods=["GET", "PATCH"], url_path="settings", url_name="settings")
    def knowledge_settings(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        if request.method == "PATCH" and "learn_from_support_enabled" in request.validated_data:
            config = learning_settings.set_learn_from_support_enabled(
                self.team, request.validated_data["learn_from_support_enabled"]
            )
        else:
            config = learning_settings.get_team_business_knowledge_config(self.team)
        return Response(self._serialize(learn_from_support_enabled=config.learn_from_support_enabled))
