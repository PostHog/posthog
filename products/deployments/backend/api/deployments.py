"""DRF wiring for the Deployment viewset (nested under DeploymentProject).

URL: `/api/projects/{team_id}/deployment_projects/{deployment_project_id}/deployments/...`

list/retrieve are read-only views over the model. Mutating actions
(create, redeploy, rollback, cancel, refresh_preview) defer all business
logic to the services layer.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Exists, OuterRef

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.permissions import APIScopePermission
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin

from ..adapters import GitHubError
from ..domain.trigger import TriggerKind
from ..models import Deployment, DeploymentEvent, DeploymentProject
from ..serializers import DeploymentEventSerializer, DeploymentSerializer
from ..serializers.deployment import (
    DeploymentActionResponseSerializer,
    DeploymentConflictResponseSerializer,
    DeploymentCreateInputSerializer,
)
from ..services import cancel, create_deployment, redeploy, refresh_preview, rollback
from .deployment_projects import DeploymentsAccessPermission


@extend_schema(
    tags=["deployments"],
    parameters=[
        OpenApiParameter(
            name="deployment_project_id",
            type=OpenApiTypes.UUID,
            location=OpenApiParameter.PATH,
            description="UUID of the parent DeploymentProject.",
        ),
    ],
)
class DeploymentViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    viewsets.ModelViewSet,
):
    """Full lifecycle viewset for Deployments.

    All deployments are scoped to a parent DeploymentProject via the URL
    parent lookup `deployment_project_id`. The viewset enforces that
    scoping in `safely_get_queryset` so a user can never see / mutate a
    deployment that doesn't belong to the project in the URL.
    """

    scope_object = "deployment"
    authentication_classes = [
        SessionAuthentication,
        PersonalAPIKeyAuthentication,
        OAuthAccessTokenAuthentication,
    ]
    permission_classes = [IsAuthenticated, APIScopePermission, DeploymentsAccessPermission]
    serializer_class = DeploymentSerializer
    # all_teams (unscoped sibling) at class-definition time — `objects` is
    # fail-closed and would raise without a team context.
    queryset = Deployment.all_teams.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["commit_sha", "commit_message", "commit_author_name", "commit_author_email", "branch"]
    ordering_fields = ["created_at", "started_at", "finished_at"]
    ordering = ["-created_at"]

    # Disable PUT/PATCH on individual deployments — they're driven by the
    # state machine, not by direct field edits. POST creates a new row,
    # the internal transitions endpoint moves it through states, and the
    # action endpoints handle redeploy/rollback/cancel.
    http_method_names = ["get", "post", "head", "options"]

    @property
    def deployment_project_id(self) -> str:
        # DRF nested router prefixes parent kwargs with `parent_lookup_`.
        return self.kwargs["parent_lookup_deployment_project_id"]

    def _should_skip_parents_filter(self) -> bool:
        # The router's default `parents_query_dict` filter assumes a `team` FK
        # and rewrites `project_id` to `team__project_id` — but `Deployment`
        # stores `team_id` as a plain `BigIntegerField`. `safely_get_queryset`
        # below applies the team scope directly using `self.team_id`.
        return True

    def safely_get_queryset(self, queryset: Any) -> Any:
        # Annotate `is_current` via Exists so the serializer can read it
        # in O(1) per row.
        is_current = Exists(
            DeploymentProject.all_teams.filter(
                current_deployment=OuterRef("pk"),
                team_id=self.team_id,
            )
        )
        qs = queryset.filter(
            team_id=self.team_id,
            project_id=self.deployment_project_id,
        ).annotate(is_current=is_current)

        # The status / author filters are list-only — applying them on
        # detail / action lookups would make `get_object()` 404 against
        # rows the URL clearly references (e.g. redeploying a cancelled
        # deployment, which is allowed). Matches the convention in
        # `_filter_queryset_by_access_level` at posthog/api/routing.py.
        if self.action != "list":
            return qs

        params = self.request.query_params if hasattr(self, "request") else {}

        status_filter = params.get("status")
        if status_filter:
            statuses = [s.strip() for s in status_filter.split(",") if s.strip()]
            qs = qs.filter(status__in=statuses)
        else:
            # Default: hide cancelled (mirrors Vercel's default filter).
            qs = qs.exclude(status=Deployment.Status.CANCELLED)

        author = params.get("author")
        if author:
            qs = qs.filter(commit_author_email__iexact=author.strip())

        return qs

    def _ensure_project_visible(self) -> None:
        """403 if the parent project doesn't belong to this team / has been deleted."""
        exists = (
            DeploymentProject.all_teams.filter(
                id=self.deployment_project_id,
                team_id=self.team_id,
            )
            .exclude(deleted=True)
            .exists()
        )
        if not exists:
            raise NotFound("Deployment project not found.")

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        # Enforced after auth/permission stacks run; `self.team_id` is set
        # by TeamAndOrgViewSetMixin in initial().
        self._ensure_project_visible()

    # ---- Create -------------------------------------------------------

    @extend_schema(
        request=DeploymentCreateInputSerializer,
        responses={
            status.HTTP_201_CREATED: DeploymentSerializer,
            status.HTTP_409_CONFLICT: OpenApiResponse(response=DeploymentConflictResponseSerializer),
            status.HTTP_502_BAD_GATEWAY: OpenApiResponse(
                description="Upstream (GitHub commit lookup or build workflow dispatch) failed."
            ),
        },
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        body = DeploymentCreateInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            deployment = create_deployment.execute(
                create_deployment.CreateDeploymentInput(
                    project_id=self.deployment_project_id,
                    team_id=self.team_id,
                    triggered_by_user_id=request.user.id if request.user.is_authenticated else None,
                    trigger_kind=TriggerKind.MANUAL,
                    commit_sha=body.validated_data.get("commit_sha") or None,
                    branch=body.validated_data.get("branch") or None,
                )
            )
        except create_deployment.ActiveDeploymentExists as exc:
            return Response(
                {
                    "detail": "A deployment is already in flight for this project.",
                    "active_deployment_id": exc.active_deployment_id,
                },
                status=status.HTTP_409_CONFLICT,
            )
        except GitHubError as exc:
            # The github adapter's contract is to bubble GitHubError up here;
            # we honour the docstring ("Translated to 502 by callers"). No DB
            # row was created — the failure happened before the atomic block.
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        except create_deployment.WorkflowDispatchFailed as exc:
            # Row has already been marked ERROR by the service; surface
            # the orphan id so operators / clients can audit.
            return Response(
                {"detail": str(exc), "deployment_id": exc.deployment_id},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(self.get_serializer(deployment).data, status=status.HTTP_201_CREATED)

    # ---- Actions ------------------------------------------------------

    @extend_schema(
        request=None,
        responses={
            status.HTTP_201_CREATED: DeploymentSerializer,
            status.HTTP_409_CONFLICT: OpenApiResponse(response=DeploymentConflictResponseSerializer),
            status.HTTP_502_BAD_GATEWAY: OpenApiResponse(
                description="Upstream (GitHub commit lookup or build workflow dispatch) failed."
            ),
        },
    )
    @action(detail=True, methods=["post"])
    def redeploy(self, request: Request, **kwargs: Any) -> Response:
        # get_object() runs safely_get_queryset (team + project filter)
        # and check_object_permissions (RBAC). Without it, the URL's
        # `deployment_project_id` is unverified — a deployment id from
        # one project could be redeployed via another project's URL.
        source = self.get_object()
        try:
            deployment = redeploy.execute(
                deployment_id=str(source.pk),
                team_id=self.team_id,
                triggered_by_user_id=request.user.id if request.user.is_authenticated else None,
            )
        except create_deployment.ActiveDeploymentExists as exc:
            return Response(
                {
                    "detail": "A deployment is already in flight for this project.",
                    "active_deployment_id": exc.active_deployment_id,
                },
                status=status.HTTP_409_CONFLICT,
            )
        except GitHubError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        except create_deployment.WorkflowDispatchFailed as exc:
            return Response(
                {"detail": str(exc), "deployment_id": exc.deployment_id},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(self.get_serializer(deployment).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=None,
        responses={
            status.HTTP_201_CREATED: DeploymentSerializer,
            status.HTTP_409_CONFLICT: OpenApiResponse(response=DeploymentConflictResponseSerializer),
            status.HTTP_502_BAD_GATEWAY: OpenApiResponse(
                description="Upstream (GitHub commit lookup or build workflow dispatch) failed."
            ),
        },
    )
    @action(detail=True, methods=["post"])
    def rollback(self, request: Request, **kwargs: Any) -> Response:
        source = self.get_object()
        try:
            deployment = rollback.execute(
                deployment_id=str(source.pk),
                team_id=self.team_id,
                triggered_by_user_id=request.user.id if request.user.is_authenticated else None,
            )
        except create_deployment.ActiveDeploymentExists as exc:
            return Response(
                {
                    "detail": "A deployment is already in flight for this project.",
                    "active_deployment_id": exc.active_deployment_id,
                },
                status=status.HTTP_409_CONFLICT,
            )
        except GitHubError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        except create_deployment.WorkflowDispatchFailed as exc:
            return Response(
                {"detail": str(exc), "deployment_id": exc.deployment_id},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(self.get_serializer(deployment).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=None,
        responses={status.HTTP_200_OK: DeploymentActionResponseSerializer},
    )
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, **kwargs: Any) -> Response:
        source = self.get_object()
        try:
            signalled = cancel.execute(deployment_id=str(source.pk), team_id=self.team_id)
        except cancel.DeploymentNotCancellable as exc:
            raise PermissionDenied(detail=str(exc))
        detail = (
            "Cancellation signal sent."
            if signalled
            else "No workflow to signal; deployment marked cancelled without a worker."
        )
        return Response({"detail": detail}, status=status.HTTP_200_OK)

    @extend_schema(request=None, responses={status.HTTP_200_OK: DeploymentSerializer})
    @action(detail=True, methods=["post"], url_path="refresh_preview")
    def refresh_preview(self, request: Request, **kwargs: Any) -> Response:
        source = self.get_object()
        deployment = refresh_preview.execute(
            deployment_id=str(source.pk),
            team_id=self.team_id,
        )
        return Response(self.get_serializer(deployment).data, status=status.HTTP_200_OK)

    @extend_schema(responses={status.HTTP_200_OK: DeploymentEventSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def events(self, request: Request, **kwargs: Any) -> Response:
        source = self.get_object()
        qs = DeploymentEvent.all_teams.filter(
            deployment_id=source.pk,
            team_id=self.team_id,
        ).order_by("-occurred_at")
        page = self.paginate_queryset(qs)
        if page is not None:
            data = DeploymentEventSerializer(page, many=True).data
            return self.get_paginated_response(data)
        data = DeploymentEventSerializer(qs, many=True).data
        return Response(data)

    @extend_schema(responses={status.HTTP_200_OK: DeploymentActionResponseSerializer})
    @action(detail=True, methods=["get"])
    def logs(self, request: Request, **kwargs: Any) -> Response:
        # Build logs land as `$log` PostHog events tagged with
        # `properties.deployment_id`. The real Logs ingest endpoint is
        # owned by another team; this stub returns an empty page until
        # the HogQL bridge lands. Frontend stream can iterate against
        # the empty shape today and we'll fill it in once the contract
        # is final.
        source = self.get_object()
        # TODO(deployments-v1): swap stub for an `execute_hogql_query` call:
        #   SELECT timestamp, level, step, line, exit_code
        #   FROM events
        #   WHERE event = '$log'
        #     AND properties.deployment_id = {deployment_id}
        #   ORDER BY timestamp ASC
        #   LIMIT 1000
        return Response(
            {"detail": f"Logs proxy not implemented yet (deployment_id={source.pk})."},
            status=status.HTTP_200_OK,
        )
