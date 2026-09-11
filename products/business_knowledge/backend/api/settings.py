from typing import Any

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import APIScopePermission, PostHogFeatureFlagPermission
from posthog.rate_limit import BurstRateThrottle, SustainedRateThrottle

from .. import learning_settings
from .serializers import BusinessKnowledgeSettingsSerializer, BusinessKnowledgeSettingsUpdateSerializer


class BusinessKnowledgeSettingsViewSet(TeamAndOrgViewSetMixin, ViewSet):
    scope_object = "business_knowledge"
    serializer_class = BusinessKnowledgeSettingsSerializer
    permission_classes = [IsAuthenticated, APIScopePermission, PostHogFeatureFlagPermission]
    posthog_feature_flag = "product-business-knowledge"
    throttle_classes = [BurstRateThrottle, SustainedRateThrottle]
    pagination_class = None
    http_method_names = ["get", "patch", "head", "options"]

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
