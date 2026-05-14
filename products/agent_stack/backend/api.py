"""DRF viewsets for agent_stack."""

from __future__ import annotations

from uuid import UUID

from django.db.models import QuerySet
from django.utils import timezone

import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from . import deploys
from .models import AgentApplication, AgentApplicationRevision, AgentApplicationSession
from .serializers import (
    AgentApplicationRevisionSerializer,
    AgentApplicationSerializer,
    AgentApplicationSessionSerializer,
    CompleteUploadRequestSerializer,
    DisableRevisionRequestSerializer,
    PreviewRevisionRequestSerializer,
    PromoteRevisionRequestSerializer,
    StartDeployRequestSerializer,
    StartDeployResponseSerializer,
    UpdateEnvRequestSerializer,
)


@extend_schema(tags=["agent_stack"])
class AgentApplicationViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """Agent applications — the deployable unit of the agent platform."""

    scope_object = "agent_application"
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "destroy",
        "start_deploy",
        "complete_upload",
        "promote",
        "preview",
        "disable_revision",
        "env",
    ]
    scope_object_read_actions = ["list", "retrieve"]
    serializer_class = AgentApplicationSerializer
    queryset = AgentApplication.objects.all()

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(deleted=False)

    def safely_get_object(self, queryset: QuerySet) -> AgentApplication | None:
        """Look up by UUID if the URL value parses as one, otherwise by slug."""
        lookup_value = self.kwargs[self.lookup_url_kwarg or self.lookup_field]
        try:
            UUID(str(lookup_value))
            field = "pk"
        except (ValueError, TypeError):
            field = "slug"
        return queryset.filter(**{field: lookup_value}).first()

    def perform_create(self, serializer: AgentApplicationSerializer) -> None:
        serializer.save(team_id=self.team_id, created_by=self.request.user)

    def perform_destroy(self, instance: AgentApplication) -> None:
        instance.deleted = True
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["deleted", "deleted_at", "updated_at"])

    # --- Deploy lifecycle ---

    def _get_revision_for_app(
        self,
        application: AgentApplication,
        revision_id: UUID,
    ) -> AgentApplicationRevision:
        try:
            return AgentApplicationRevision.objects.get(
                pk=revision_id,
                application=application,
                team_id=self.team_id,
            )
        except AgentApplicationRevision.DoesNotExist as e:
            raise NotFound("Revision not found") from e

    @validated_request(
        request_serializer=StartDeployRequestSerializer,
        responses={
            201: OpenApiResponse(response=StartDeployResponseSerializer),
            503: OpenApiResponse(description="Object storage unavailable"),
        },
    )
    @action(detail=True, methods=["post"], url_path="start_deploy")
    def start_deploy(self, request: ValidatedRequest, **kwargs) -> Response:
        """Create a pending revision and return a presigned upload target."""
        application = self.get_object()
        data = request.validated_data
        try:
            revision, presigned = deploys.start_deploy(
                application=application,
                bundle_sha256=data["bundle_sha256"],
                bundle_size=data["bundle_size"],
                top_level_config=data["top_level_config"],
                created_by_id=getattr(request.user, "id", None),
            )
        except deploys.StorageUnavailableError:
            return Response(
                {"detail": "object storage is unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(
            StartDeployResponseSerializer(
                {
                    "revision_id": revision.id,
                    "upload_url": presigned["url"],
                    "upload_fields": presigned["fields"],
                    "expires_at": presigned["expires_at"],
                    "max_size": revision.bundle_size or 0,
                    "required_sha256": revision.bundle_sha256,
                }
            ).data,
            status=status.HTTP_201_CREATED,
        )

    @validated_request(
        request_serializer=CompleteUploadRequestSerializer,
        responses={
            200: OpenApiResponse(response=AgentApplicationRevisionSerializer),
            409: OpenApiResponse(description="Revision in wrong state"),
        },
    )
    @action(detail=True, methods=["post"], url_path="complete_upload")
    def complete_upload(self, request: ValidatedRequest, **kwargs) -> Response:
        """v1: transitions the revision straight to state=ready."""
        application = self.get_object()
        revision = self._get_revision_for_app(application, request.validated_data["revision_id"])
        try:
            revision = deploys.complete_upload(revision=revision)
        except deploys.RevisionStateError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        return Response(AgentApplicationRevisionSerializer(revision).data)

    @validated_request(
        request_serializer=PromoteRevisionRequestSerializer,
        responses={
            200: OpenApiResponse(response=AgentApplicationRevisionSerializer),
            409: OpenApiResponse(description="Revision is not ready"),
        },
    )
    @action(detail=True, methods=["post"], url_path="promote")
    def promote(self, request: ValidatedRequest, **kwargs) -> Response:
        """Promote a ready revision to live. Demotes the previous live revision atomically."""
        application = self.get_object()
        revision = self._get_revision_for_app(application, request.validated_data["revision_id"])
        try:
            revision = deploys.promote_revision(revision=revision)
        except deploys.RevisionStateError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        return Response(AgentApplicationRevisionSerializer(revision).data)

    @validated_request(
        request_serializer=PreviewRevisionRequestSerializer,
        responses={
            200: OpenApiResponse(response=AgentApplicationRevisionSerializer),
            409: OpenApiResponse(description="Revision is not ready"),
        },
    )
    @action(detail=True, methods=["post"], url_path="preview")
    def preview(self, request: ValidatedRequest, **kwargs) -> Response:
        """Mark a ready revision as preview. Multiple previews can coexist; no siblings demoted."""
        application = self.get_object()
        revision = self._get_revision_for_app(application, request.validated_data["revision_id"])
        try:
            revision = deploys.preview_revision(revision=revision)
        except deploys.RevisionStateError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        return Response(AgentApplicationRevisionSerializer(revision).data)

    @validated_request(
        request_serializer=DisableRevisionRequestSerializer,
        responses={200: OpenApiResponse(response=AgentApplicationRevisionSerializer)},
    )
    @action(detail=True, methods=["post"], url_path="disable_revision")
    def disable_revision(self, request: ValidatedRequest, **kwargs) -> Response:
        """Set a revision's deployment_status to disabled. Pulls it out of any traffic role."""
        application = self.get_object()
        revision = self._get_revision_for_app(application, request.validated_data["revision_id"])
        revision = deploys.disable_revision(revision=revision)
        return Response(AgentApplicationRevisionSerializer(revision).data)

    @validated_request(
        request_serializer=UpdateEnvRequestSerializer,
        responses={200: OpenApiResponse(response=AgentApplicationSerializer)},
    )
    @action(detail=True, methods=["put"], url_path="env")
    def env(self, request: ValidatedRequest, **kwargs) -> Response:
        """Replace the application's encrypted `.env`. Plaintext is not returned."""
        application = self.get_object()
        application = deploys.update_env(application=application, env=request.validated_data["env"])
        return Response(AgentApplicationSerializer(application).data)


def _filter_by_parent_application(queryset: QuerySet, lookup_value: str) -> QuerySet:
    """Filter a child queryset to rows whose `application` matches the URL kwarg.

    Accepts either an application UUID or a slug — symmetric with the parent
    viewset's `safely_get_object` so nested URLs work both ways.
    """
    try:
        UUID(str(lookup_value))
        return queryset.filter(application_id=lookup_value)
    except (ValueError, TypeError):
        return queryset.filter(application__slug=lookup_value, application__deleted=False)


@extend_schema(tags=["agent_stack"])
class AgentApplicationRevisionViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """Revisions for an application — read-only, nested under agent_applications."""

    scope_object = "agent_application"
    scope_object_read_actions = ["list", "retrieve"]
    serializer_class = AgentApplicationRevisionSerializer
    queryset = AgentApplicationRevision.objects.all().order_by("-created_at")
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["deployment_status", "state"]

    def _should_skip_parents_filter(self) -> bool:
        # We resolve the parent slug-or-UUID ourselves below; the auto-filter
        # only knows how to match by id, which breaks for slugs.
        return True

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return _filter_by_parent_application(
            queryset.filter(team_id=self.team_id),
            self.parents_query_dict["application_id"],
        )


class AgentApplicationSessionFilter(django_filters.FilterSet):
    created_after = django_filters.IsoDateTimeFilter(
        field_name="created_at",
        lookup_expr="gte",
        help_text="Inclusive lower bound on created_at (ISO-8601). Used by `ass logs --follow` polling.",
    )
    created_before = django_filters.IsoDateTimeFilter(
        field_name="created_at",
        lookup_expr="lt",
        help_text="Exclusive upper bound on created_at (ISO-8601).",
    )

    class Meta:
        model = AgentApplicationSession
        fields = ["revision", "state", "parent_run_id"]


@extend_schema(tags=["agent_stack"])
class AgentApplicationSessionViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """Sessions for an application — read-only, nested under agent_applications."""

    scope_object = "agent_application"
    scope_object_read_actions = ["list", "retrieve"]
    serializer_class = AgentApplicationSessionSerializer
    queryset = AgentApplicationSession.objects.all().order_by("-created_at")
    filter_backends = [DjangoFilterBackend]
    filterset_class = AgentApplicationSessionFilter

    def _should_skip_parents_filter(self) -> bool:
        return True

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return _filter_by_parent_application(
            queryset.filter(team_id=self.team_id),
            self.parents_query_dict["application_id"],
        )
