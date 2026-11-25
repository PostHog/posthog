from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import ProjectSecretAPIKeyAuthentication
from posthog.permissions import APIScopePermission, PostHogFeatureFlagPermission

from ..key_libraries import key_library_id
from .settings import CanonicalTeamTokenPermission
from .throttles import KNOWLEDGE_THROTTLES


class KnowledgeAccessSerializer(serializers.Serializer):
    project_id = serializers.IntegerField(help_text="ID of the project whose business knowledge the caller reads.")
    is_limited = serializers.BooleanField(
        help_text="True when the caller reads one library. False when it reads all business knowledge in the project."
    )
    library_id = serializers.UUIDField(
        allow_null=True, help_text="The library a limited caller reads. Null when the caller is not limited."
    )


class KnowledgeAccessViewSet(TeamAndOrgViewSetMixin, ViewSet):
    scope_object = "business_knowledge"
    authentication_classes = [ProjectSecretAPIKeyAuthentication]
    # Every action listed here must apply the key's library limit from `key_libraries`.
    psak_allowed_actions = ["access"]
    permission_classes = [
        IsAuthenticated,
        APIScopePermission,
        PostHogFeatureFlagPermission,
        CanonicalTeamTokenPermission,
    ]
    posthog_feature_flag = "product-business-knowledge"
    throttle_classes = KNOWLEDGE_THROTTLES
    pagination_class = None

    @validated_request(
        query_serializer=None,
        responses={200: OpenApiResponse(response=KnowledgeAccessSerializer)},
        summary="Get what the caller can read",
        description=(
            "The project and, for a project secret API key limited to a library, the library the caller reads. "
            "A project secret API key can call this with `@current` as the project ID to learn its own project."
        ),
        operation_id="business_knowledge_access_retrieve",
    )
    @action(detail=False, methods=["GET"], url_path="access", required_scopes=["business_knowledge:read"])
    def access(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        library_id = key_library_id(request)
        return Response(
            KnowledgeAccessSerializer(
                {
                    "project_id": self.team.parent_team_id or self.team_id,
                    "is_limited": library_id is not None,
                    "library_id": library_id,
                }
            ).data
        )
