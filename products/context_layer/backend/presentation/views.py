from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, Throttled, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import APIScopePermission, PostHogFeatureFlagPermission

from products.context_layer.backend.facade import api as facade
from products.context_layer.backend.presentation.serializers import (
    CommitBundleSerializer,
    ContextLayerStatusSerializer,
    HeadConflictSerializer,
    LintErrorSerializer,
    WikiExportSerializer,
    WikiPageSerializer,
    WikiPageWriteSerializer,
    WikiTreeSerializer,
)


def _store_error_response(error: facade.ContextLayerStoreError) -> Response:
    """One mapping from store errors to HTTP for every action, so new writers
    added in later layers cannot drift from this contract."""
    if isinstance(error, facade.RepoNotFoundError):
        raise NotFound("The context layer is not enabled for this organization.") from error
    if isinstance(error, facade.InvalidPagePathError):
        raise ValidationError(str(error)) from error
    if isinstance(error, facade.RepoLockUnavailableError):
        raise Throttled(detail=str(error))
    if isinstance(error, facade.PageNotFoundError):
        raise NotFound(str(error)) from error
    if isinstance(error, facade.HeadConflictError):
        return Response(
            {
                "detail": "The wiki changed since this edit was based; re-read and retry.",
                "current_head": error.current_head,
            },
            status=status.HTTP_409_CONFLICT,
        )
    if isinstance(error, facade.BundleConflictError):
        return Response({"detail": str(error)}, status=status.HTTP_409_CONFLICT)
    if isinstance(error, facade.LintFailedError):
        return Response(
            {"detail": "The change violates the wiki structure.", "errors": error.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )
    raise error


@extend_schema(tags=["context_layer"])
class ContextLayerViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """The organization's context wiki: a git repo of Markdown pages hosted by PostHog."""

    # No authentication_classes override: the mixin already appends PostHog's
    # session/PAT/OAuth authenticators, and DRF's stock SessionAuthentication
    # would run first and skip enforce_two_factor.
    # The flag is the rollout boundary: the whole surface stays off until the
    # organization opts into `context-layer`.
    posthog_feature_flag = "context-layer"
    permission_classes = [IsAuthenticated, APIScopePermission, PostHogFeatureFlagPermission]
    scope_object = "organization"
    scope_object_read_actions = ["status", "tree", "page", "export"]
    scope_object_write_actions = ["enable", "update_page", "commits"]

    @extend_schema(
        request=None,
        responses={201: ContextLayerStatusSerializer},
        summary="Enable the context layer",
        description=(
            "Create the organization's wiki with the default structure and import existing channel "
            "CONTEXT.md documents once. Idempotent."
        ),
    )
    @action(methods=["POST"], detail=False)
    def enable(self, request: Request, **kwargs) -> Response:
        user_id = request.user.id if request.user and request.user.is_authenticated else None
        try:
            config = facade.enable_context_layer(self.organization.id, created_by_id=user_id)
        except facade.RestrictedProjectsError as error:
            raise ValidationError(str(error)) from error
        except facade.ContextLayerStoreError as error:
            return _store_error_response(error)
        return Response(
            ContextLayerStatusSerializer({"head_sha": config.head_sha}).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(
        responses={
            200: ContextLayerStatusSerializer,
            404: OpenApiResponse(description="The context layer is not enabled."),
        },
        summary="Get the wiki head",
    )
    @action(methods=["GET"], detail=False)
    def status(self, request: Request, **kwargs) -> Response:
        try:
            config = facade.get_config(self.organization.id)
        except facade.ContextLayerStoreError as error:
            return _store_error_response(error)
        return Response(ContextLayerStatusSerializer({"head_sha": config.head_sha}).data)

    @extend_schema(
        responses={200: WikiTreeSerializer, 404: OpenApiResponse(description="The context layer is not enabled.")},
        summary="List wiki pages",
    )
    @action(methods=["GET"], detail=False)
    def tree(self, request: Request, **kwargs) -> Response:
        try:
            wiki_tree = facade.get_tree(self.organization.id)
        except facade.ContextLayerStoreError as error:
            return _store_error_response(error)
        return Response(WikiTreeSerializer(wiki_tree).data)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="path", type=str, required=True, description="Repo-relative Markdown path of the page to read."
            )
        ],
        responses={200: WikiPageSerializer, 404: OpenApiResponse(description="No page at this path.")},
        summary="Read a wiki page",
    )
    @action(methods=["GET"], detail=False, url_path="pages", url_name="pages")
    def page(self, request: Request, **kwargs) -> Response:
        try:
            wiki_page = facade.get_page(self.organization.id, request.query_params.get("path", ""))
        except facade.ContextLayerStoreError as error:
            return _store_error_response(error)
        return Response(WikiPageSerializer(wiki_page).data)

    @extend_schema(
        request=WikiPageWriteSerializer,
        responses={
            200: ContextLayerStatusSerializer,
            400: LintErrorSerializer,
            409: HeadConflictSerializer,
        },
        summary="Create or replace a wiki page",
    )
    @page.mapping.put
    def update_page(self, request: Request, **kwargs) -> Response:
        serializer = WikiPageWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        author = (
            facade.CommitAuthor(name=user.first_name or user.email, email=user.email)
            if user and user.is_authenticated
            else None
        )
        try:
            head_sha = facade.write_page(
                self.organization.id,
                path=serializer.validated_data["path"],
                content=serializer.validated_data["content"],
                base_head=serializer.validated_data.get("base_head"),
                author=author,
            )
        except facade.ContextLayerStoreError as error:
            return _store_error_response(error)
        return Response(ContextLayerStatusSerializer({"head_sha": head_sha}).data)

    @extend_schema(
        request=CommitBundleSerializer,
        responses={
            200: ContextLayerStatusSerializer,
            400: LintErrorSerializer,
            409: OpenApiResponse(description="The posted commits conflict with the current head; re-pull and retry."),
        },
        summary="Land agent commits from a git bundle",
    )
    @action(methods=["POST"], detail=False, parser_classes=[MultiPartParser, FormParser])
    def commits(self, request: Request, **kwargs) -> Response:
        serializer = CommitBundleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        bundle_bytes = serializer.validated_data["bundle"].read()
        try:
            head_sha = facade.land_commit_bundle(self.organization.id, bundle_bytes)
        except facade.ContextLayerStoreError as error:
            return _store_error_response(error)
        return Response(ContextLayerStatusSerializer({"head_sha": head_sha}).data)

    @extend_schema(
        responses={200: WikiExportSerializer},
        summary="Export the wiki",
        description="A short-lived download URL for the wiki's current bundle: the whole repo and its history, one file, standard git.",
    )
    @action(methods=["GET"], detail=False)
    def export(self, request: Request, **kwargs) -> Response:
        try:
            bundle = facade.get_bundle_export(self.organization.id)
        except facade.ContextLayerStoreError as error:
            return _store_error_response(error)
        return Response(WikiExportSerializer({"url": bundle.url, "head_sha": bundle.head_sha}).data)
