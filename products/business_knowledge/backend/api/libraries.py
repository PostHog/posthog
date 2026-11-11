from functools import cached_property
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import exceptions, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import APIScopePermission, PostHogFeatureFlagPermission
from posthog.rate_limit import BurstRateThrottle, SustainedRateThrottle

from products.access_control.backend.facade.user_access_control import UserAccessControl

from ..github_repos import selected_repositories
from ..libraries import (
    LibraryNotFound,
    LibraryRejected,
    create_library,
    delete_library,
    get_library,
    list_libraries,
    rename_library,
    replace_library_repos,
    replace_library_sources,
    visible_repos,
)
from ..models import KnowledgeLibrary
from .library_serializers import (
    KnowledgeLibraryCreateSerializer,
    KnowledgeLibrarySerializer,
    KnowledgeLibraryUpdateSerializer,
)
from .settings import CanonicalTeamTokenPermission, canonical_user_access_control

_READ_ACTIONS = frozenset({"list", "retrieve"})
_WRITE_ACTIONS = frozenset({"create", "partial_update", "destroy"})


class KnowledgeLibraryViewSet(TeamAndOrgViewSetMixin, ViewSet):
    scope_object = "business_knowledge"
    # A library is project-wide, not an access-controlled object. Without this flag, editor
    # access to one source passes the list check for a member whose resource-level access is "none".
    requires_resource_level_access = True
    permission_classes = [
        IsAuthenticated,
        APIScopePermission,
        PostHogFeatureFlagPermission,
        CanonicalTeamTokenPermission,
    ]
    posthog_feature_flag = "product-business-knowledge"
    throttle_classes = [BurstRateThrottle, SustainedRateThrottle]
    pagination_class = None

    @cached_property
    def user_access_control(self) -> UserAccessControl:
        # Libraries belong to the parent project, so its grants decide for every environment.
        return canonical_user_access_control(self)

    def dangerously_get_required_scopes(self, request: Request, view: Any) -> list[str] | None:
        if self.action in _WRITE_ACTIONS:
            return ["business_knowledge:write"]
        if self.action in _READ_ACTIONS:
            return ["business_knowledge:read"]
        return None

    @validated_request(
        query_serializer=None,
        responses={200: OpenApiResponse(response=KnowledgeLibrarySerializer(many=True))},
        summary="List business knowledge libraries",
        description="Libraries in this project. The default library is first.",
        operation_id="business_knowledge_libraries_list",
    )
    def list(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        libraries = list_libraries(self.team_id)
        repos = visible_repos(self.team_id, [library.id for library in libraries], self._allowlist())
        return Response(
            KnowledgeLibrarySerializer(
                [_library_payload(library, repos.get(library.id, [])) for library in libraries],
                many=True,
            ).data
        )

    @validated_request(
        request_serializer=KnowledgeLibraryCreateSerializer,
        responses={201: OpenApiResponse(response=KnowledgeLibrarySerializer)},
        summary="Create a business knowledge library",
        operation_id="business_knowledge_libraries_create",
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        try:
            library = create_library(self.team_id, request.validated_data["name"])
        except LibraryRejected as exc:
            raise exceptions.ValidationError(exc.errors) from exc
        return Response(self._one(library), status=status.HTTP_201_CREATED)

    @extend_schema(
        responses={200: KnowledgeLibrarySerializer},
        summary="Get a business knowledge library",
        operation_id="business_knowledge_libraries_retrieve",
    )
    def retrieve(self, request: Request, pk: str, **kwargs: Any) -> Response:
        return Response(self._one(self._get(pk)))

    @validated_request(
        request_serializer=KnowledgeLibraryUpdateSerializer,
        responses={200: OpenApiResponse(response=KnowledgeLibrarySerializer)},
        summary="Rename a library or replace its sources and repositories",
        description=(
            "Send only the fields you want to change. `source_ids` replaces every source in the library. "
            "`repos` replaces this environment's repositories and leaves repositories that only another environment allows."
        ),
        operation_id="business_knowledge_libraries_partial_update",
    )
    def partial_update(self, request: ValidatedRequest, pk: str, **kwargs: Any) -> Response:
        library_id = _parse_library_id(pk)
        data = request.validated_data
        allowlist = self._allowlist() if "repos" in data else set()
        try:
            with transaction.atomic():
                library = get_library(self.team_id, library_id)
                if "name" in data:
                    library = rename_library(self.team_id, library.id, data["name"])
                if "source_ids" in data:
                    library = replace_library_sources(self.team_id, library.id, data["source_ids"])
                if "repos" in data:
                    library = replace_library_repos(
                        self.team_id,
                        library.id,
                        data["repos"],
                        environment_allowlist=allowlist,
                    )
        except LibraryNotFound:
            raise exceptions.NotFound() from None
        except LibraryRejected as exc:
            raise exceptions.ValidationError(exc.errors) from exc
        return Response(self._one(library))

    @extend_schema(
        responses={204: None},
        summary="Delete a business knowledge library",
        description="Removes the library and its links. Sources, documents, and selected repositories stay.",
        operation_id="business_knowledge_libraries_destroy",
    )
    def destroy(self, request: Request, pk: str, **kwargs: Any) -> Response:
        try:
            delete_library(self.team_id, _parse_library_id(pk))
        except LibraryNotFound:
            raise exceptions.NotFound() from None
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _get(self, pk: str) -> KnowledgeLibrary:
        try:
            return get_library(self.team_id, _parse_library_id(pk))
        except LibraryNotFound:
            raise exceptions.NotFound() from None

    def _one(self, library: KnowledgeLibrary) -> dict[str, Any]:
        repos = visible_repos(self.team_id, [library.id], self._allowlist()).get(library.id, [])
        return KnowledgeLibrarySerializer(_library_payload(library, repos)).data

    def _allowlist(self) -> set[str]:
        _, repos = selected_repositories(self.team)
        return set(repos)


def _parse_library_id(pk: str) -> UUID:
    try:
        return UUID(pk)
    except (ValueError, DjangoValidationError):
        raise exceptions.NotFound() from None


def _library_payload(library: KnowledgeLibrary, repos: list[str]) -> dict[str, Any]:
    return {
        "id": library.id,
        "name": library.name,
        "is_default": library.is_default,
        "source_count": getattr(library, "source_count", 0),
        "repos": repos,
    }
