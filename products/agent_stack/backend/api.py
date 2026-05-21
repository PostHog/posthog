"""DRF viewsets for agent_stack."""

from __future__ import annotations

import logging
from uuid import UUID

from django.conf import settings
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.dateparse import parse_datetime

import requests as http_requests
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import (
    serializers as drf_serializers,
    status,
    viewsets,
)
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import ProductKey

from posthog.api.log_entries import fetch_log_entries
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Feature, tag_queries

from . import deploys
from .models import AgentApplication, AgentApplicationRevision
from .serializers import (
    AgentApplicationRevisionSerializer,
    AgentApplicationSerializer,
    CompleteUploadRequestSerializer,
    DisableRevisionRequestSerializer,
    PatchEnvKeysRequestSerializer,
    PreviewRevisionRequestSerializer,
    PromoteRevisionRequestSerializer,
    StartDeployRequestSerializer,
    StartDeployResponseSerializer,
    UpdateEnvRequestSerializer,
)

logger = logging.getLogger(__name__)


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
        """Promote a ready revision to live. Blocked if required secrets are missing."""
        application = self.get_object()
        revision = self._get_revision_for_app(application, request.validated_data["revision_id"])
        try:
            revision = deploys.promote_revision(revision=revision, application=application)
        except deploys.RevisionStateError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except deploys.MissingSecretsError as e:
            return Response(
                {"detail": str(e), "missing_secrets": e.missing},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(AgentApplicationRevisionSerializer(revision).data)

    @validated_request(
        request_serializer=PreviewRevisionRequestSerializer,
        responses={
            200: OpenApiResponse(response=AgentApplicationRevisionSerializer),
            409: OpenApiResponse(description="Revision is not ready or secrets missing"),
        },
    )
    @action(detail=True, methods=["post"], url_path="preview")
    def preview(self, request: ValidatedRequest, **kwargs) -> Response:
        """Mark a ready revision as preview. Blocked if required secrets are missing."""
        application = self.get_object()
        revision = self._get_revision_for_app(application, request.validated_data["revision_id"])
        try:
            revision = deploys.preview_revision(revision=revision, application=application)
        except deploys.RevisionStateError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except deploys.MissingSecretsError as e:
            return Response(
                {"detail": str(e), "missing_secrets": e.missing},
                status=status.HTTP_409_CONFLICT,
            )
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

    @action(detail=True, methods=["put", "patch"], url_path="env")
    def env(self, request: ValidatedRequest, **kwargs) -> Response:
        """PUT: replace the entire env. PATCH: merge individual keys (set to null to remove)."""
        application = self.get_object()
        if request.method == "PATCH":
            serializer = PatchEnvKeysRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            application = deploys.patch_env_keys(
                application=application,
                keys=serializer.validated_data["keys"],
            )
        else:
            serializer = UpdateEnvRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            application = deploys.update_env(
                application=application,
                env=serializer.validated_data["env"],
            )
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


def _resolve_application_id(lookup_value: str, team_id: int) -> str | None:
    """Resolve a slug-or-UUID to the application's UUID string."""
    try:
        UUID(str(lookup_value))
        return str(lookup_value)
    except (ValueError, TypeError):
        app = AgentApplication.objects.filter(slug=lookup_value, deleted=False, team_id=team_id).first()
        return str(app.id) if app else None


class AgentApplicationSessionProxyPlaceholderSerializer(drf_serializers.Serializer):
    """Placeholder so drf-spectacular has a named serializer for the proxy
    viewset; actual response shapes are declared per-action via @extend_schema.
    """


@extend_schema(tags=["agent_stack"])
@extend_schema_view(
    list=extend_schema(
        operation_id="agent_applications_sessions_list",
        responses={200: OpenApiResponse(response=OpenApiTypes.OBJECT, description="List of sessions")},
        description="List sessions for an agent application (proxied from agent-janitor).",
    ),
    retrieve=extend_schema(
        operation_id="agent_applications_sessions_retrieve",
        responses={200: OpenApiResponse(response=OpenApiTypes.OBJECT, description="Single session detail")},
        description="Fetch a single session by id (proxied from agent-janitor).",
    ),
    cancel=extend_schema(
        operation_id="agent_applications_sessions_cancel",
        responses={200: OpenApiResponse(response=OpenApiTypes.OBJECT, description="Updated session")},
        description="Cancel a running session (proxied from agent-janitor).",
    ),
    logs=extend_schema(
        operation_id="agent_applications_sessions_logs",
        responses={200: OpenApiResponse(response=OpenApiTypes.OBJECT, description="Log entries page")},
        description="Read per-session log entries from ClickHouse.",
    ),
)
class AgentApplicationSessionProxyViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Proxy to the agent-janitor service for session list/detail/cancel.

    Django authenticates + authorizes, then forwards to the janitor's internal
    HTTP API. The janitor owns the session schema — we pass its response through.
    """

    scope_object = "agent_application"
    scope_object_read_actions = ["list", "retrieve", "logs"]
    scope_object_write_actions = ["cancel"]
    # Opaque-JSON proxy responses: give drf-spectacular a *named* placeholder
    # serializer (the bare `Serializer` base has no name and trips schema
    # generation). Per-action @extend_schema decorators above declare the
    # actual response shapes.
    serializer_class = AgentApplicationSessionProxyPlaceholderSerializer

    def _janitor_url(self, path: str) -> str:
        base = getattr(settings, "AGENT_JANITOR_BASE_URL", "http://localhost:3031")
        return f"{base.rstrip('/')}{path}"

    def _janitor_headers(self) -> dict[str, str]:
        key = getattr(settings, "AGENT_JANITOR_SHARED_KEY", "")
        return {"x-internal-key": key} if key else {}

    def _resolve_app_id(self) -> str:
        lookup = self.parents_query_dict.get("application_id", "")
        app_id = _resolve_application_id(lookup, self.team_id)
        if not app_id:
            raise NotFound("Application not found")
        return app_id

    def list(self, request: Request, **kwargs) -> Response:
        """List sessions for this application via the janitor."""
        app_id = self._resolve_app_id()
        params = {
            "application_id": app_id,
            "team_id": str(self.team_id),
        }
        for key in ("status", "limit", "created_before"):
            val = request.query_params.get(key)
            if val:
                params[key] = val
        try:
            resp = http_requests.get(
                self._janitor_url("/internal/sessions"), params=params, headers=self._janitor_headers(), timeout=10
            )
        except http_requests.ConnectionError:
            return Response(
                {"detail": "agent-janitor service is not reachable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(resp.json(), status=resp.status_code)

    def retrieve(self, request: Request, pk: str, **kwargs) -> Response:
        """Get a single session by id via the janitor."""
        try:
            resp = http_requests.get(
                self._janitor_url(f"/internal/sessions/{pk}"), headers=self._janitor_headers(), timeout=10
            )
        except http_requests.ConnectionError:
            return Response(
                {"detail": "agent-janitor service is not reachable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(resp.json(), status=resp.status_code)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request: Request, pk: str, **kwargs) -> Response:
        """Cancel a running session via the janitor."""
        try:
            resp = http_requests.post(
                self._janitor_url(f"/internal/sessions/{pk}/cancel"), headers=self._janitor_headers(), timeout=10
            )
        except http_requests.ConnectionError:
            return Response(
                {"detail": "agent-janitor service is not reachable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(resp.json(), status=resp.status_code)

    @action(detail=True, methods=["get"], url_path="logs")
    def logs(self, request: Request, pk: str, **kwargs) -> Response:
        """Read per-session logs from ClickHouse `log_entries` (`log_source='agent_session'`).

        Poll-friendly: pass `?after=<iso-timestamp>` to get only entries newer
        than the previous batch. `next_after` in the response is the timestamp
        of the newest entry returned — feed it back as `?after=` next poll.
        """
        app_id = self._resolve_app_id()
        try:
            after = parse_datetime(request.query_params.get("after")) if request.query_params.get("after") else None
        except ValueError:
            return Response({"detail": "invalid `after` timestamp"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            limit = max(1, min(int(request.query_params.get("limit", 200)), 500))
        except (TypeError, ValueError):
            limit = 200

        try:
            # `sync_execute` requires query attribution. No agent-specific
            # ProductKey exists yet — borrow PIPELINE_DESTINATIONS to match
            # the existing log_entries.py default. Replace once an
            # AGENT_STACK key lands in the schema.
            tag_queries(product=ProductKey.PIPELINE_DESTINATIONS, feature=Feature.QUERY)
            rows = fetch_log_entries(
                team_id=self.team_id,
                log_source="agent_session",
                log_source_id=app_id,
                instance_id=pk,
                after=after,
                limit=limit,
            )
        except Exception:
            # Full exception (ClickHouse error codes, internal hostnames, stack)
            # goes to the server log only — never echo it to the API client.
            logger.exception(
                "agent_stack.session_logs query failed",
                extra={"application_id": app_id, "session_id": pk, "team_id": self.team_id},
            )
            return Response(
                {"detail": "Log store is temporarily unavailable. Retry shortly."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        # Rows come back DESC by timestamp; flip to oldest-first for the UI.
        entries = [
            {"timestamp": r.timestamp.isoformat(), "level": r.level, "message": r.message} for r in reversed(rows)
        ]
        next_after = rows[0].timestamp.isoformat() if rows else None
        return Response({"entries": entries, "next_after": next_after})
