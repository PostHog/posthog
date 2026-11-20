from typing import Any
from uuid import UUID

from django.db import transaction

from drf_spectacular.utils import OpenApiResponse
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.project_secret_api_key import ProjectSecretAPIKeySerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.permissions import (
    PostHogFeatureFlagPermission,
    TeamMemberStrictManagementPermission,
    TimeSensitiveActionPermission,
)

from ..key_libraries import key_limits, limit_key_to_library
from ..libraries import LibraryNotFound
from .key_serializers import KnowledgeKeyCreateSerializer, KnowledgeKeySerializer

_READ_SCOPE = "business_knowledge:read"


class KnowledgeKeyViewSet(TeamAndOrgViewSetMixin, ViewSet):
    # These are project secret API keys, so this route has the gate of the endpoint that manages them.
    scope_object = "project"
    scope_object_write_actions = ["create"]
    permission_classes = [
        TimeSensitiveActionPermission,
        TeamMemberStrictManagementPermission,
        PostHogFeatureFlagPermission,
    ]
    posthog_feature_flag = "product-business-knowledge"
    pagination_class = None

    @validated_request(
        query_serializer=None,
        responses={200: OpenApiResponse(response=KnowledgeKeySerializer(many=True))},
        summary="List the keys that read business knowledge",
        description=(
            "Project secret API keys in this project with the business_knowledge:read scope, newest first, "
            "and the library each one is limited to."
        ),
        operation_id="business_knowledge_keys_list",
    )
    def list(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        self._require_parent_project()
        keys = list(
            ProjectSecretAPIKey.objects.filter(team_id=self.team_id, scopes__contains=[_READ_SCOPE]).order_by(
                "-created_at"
            )
        )
        limits = key_limits(self.team_id, [key.id for key in keys])
        return Response(
            KnowledgeKeySerializer(
                [_key_payload(key, key.id in limits, limits.get(key.id)) for key in keys], many=True
            ).data
        )

    @validated_request(
        request_serializer=KnowledgeKeyCreateSerializer,
        responses={201: OpenApiResponse(response=KnowledgeKeySerializer)},
        summary="Create a key that reads business knowledge",
        description=(
            "Creates a project secret API key with the business_knowledge:read scope. The key reads one library, "
            "or all business knowledge in the project when library_id is null. "
            "The response is the only place the key value appears. Delete or roll the key through the project "
            "secret API keys endpoint."
        ),
        operation_id="business_knowledge_keys_create",
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        self._require_parent_project()
        library_id: UUID | None = request.validated_data["library_id"]
        serializer = ProjectSecretAPIKeySerializer(
            data={"label": request.validated_data["label"], "scopes": [_READ_SCOPE]},
            context={"request": request, "view": self},
        )
        serializer.is_valid(raise_exception=True)
        try:
            # One transaction, so a key meant for one library never reads the whole project, even when the limit fails.
            with transaction.atomic():
                key = serializer.save()
                if library_id is not None:
                    limit_key_to_library(self.team_id, key, library_id)
        except LibraryNotFound:
            raise exceptions.ValidationError({"library_id": "This library was not found."}) from None
        payload = _key_payload(key, library_id is not None, library_id)
        payload["value"] = key._value
        return Response(KnowledgeKeySerializer(payload).data, status=status.HTTP_201_CREATED)

    def _require_parent_project(self) -> None:
        # The knowledge routes refuse a key from a child environment, so a key made here would read nothing.
        if self.team.parent_team_id:
            raise exceptions.ValidationError(
                f"Business knowledge belongs to project ID {self.team.parent_team_id}. Manage its keys in that project."
            )


def _key_payload(key: ProjectSecretAPIKey, is_limited: bool, library_id: UUID | None) -> dict[str, Any]:
    return {
        "id": key.id,
        "label": key.label,
        "mask_value": key.mask_value,
        "value": None,
        "created_at": key.created_at,
        "last_used_at": key.last_used_at,
        "is_limited": is_limited,
        "library_id": library_id,
    }
