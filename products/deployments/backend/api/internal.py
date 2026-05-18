"""Service-to-service endpoints for the Deployments product.

The Temporal build worker posts status transitions and lifecycle events
to this viewset. Auth is `X-Internal-Api-Secret` against
`settings.INTERNAL_API_SECRET`. Excluded from the OpenAPI schema —
these endpoints are owned by infrastructure, not customer-facing.

Routes (wired in `posthog/urls.py`, not via the DRF router — matching
the precedent at `products/signals/backend/views.py:142-172`):

- POST /api/internal/deployments/{deployment_id}/transitions/
- POST /api/internal/deployments/{deployment_id}/events/

The `transitions` handler is the ONLY mutator of `Deployment.status`
(see services/update_status.py). The `events` handler is an append-only
sink for `DeploymentEvent` rows the worker emits during build.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import InternalAPIAuthentication
from posthog.models.scoping import team_scope

from ..domain.status import InvalidStatusTransition, Status
from ..domain.trigger import ErrorStep
from ..models import Deployment, DeploymentEvent
from ..serializers import DeploymentSerializer
from ..services import update_status

logger = structlog.get_logger(__name__)


class InternalTransitionInputSerializer(serializers.Serializer):
    """Body for POST /api/internal/deployments/{id}/transitions/.

    The build worker posts this after each lifecycle activity completes
    (dispatched → initializing → building → ready / error / cancelled).
    """

    status = serializers.ChoiceField(
        choices=[s.value for s in Status],
        help_text="Target deployment status. Validated against domain.status.VALID_TRANSITIONS.",
    )
    cloudflare_deployment_id = serializers.CharField(
        max_length=128,
        required=False,
        allow_blank=True,
        help_text="Cloudflare Pages deployment id assigned once publish succeeds.",
    )
    deployment_url = serializers.URLField(
        max_length=1024,
        required=False,
        allow_blank=True,
        help_text="Public URL the build was published to. Set on ready transitions.",
    )
    error_message = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Human-readable failure detail. Set on error transitions.",
    )
    error_step = serializers.ChoiceField(
        choices=[s.value for s in ErrorStep],
        required=False,
        allow_blank=True,
        help_text="Build step that failed (dispatch/clone/install/build/publish).",
    )
    started_at = serializers.DateTimeField(
        required=False,
        help_text="Optional started_at override (worker-time). If omitted, auto-stamped on INITIALIZING.",
    )
    finished_at = serializers.DateTimeField(
        required=False,
        help_text="Optional finished_at override (worker-time). If omitted, auto-stamped on terminal status.",
    )


class InternalEventInputSerializer(serializers.Serializer):
    """Body for POST /api/internal/deployments/{id}/events/.

    Append-only audit log entries emitted by the build worker as
    activities run (start/finish of each step, preview-capture outcome,
    etc.). Free-form payload by design — the timeline UI is the only
    consumer and we want schema-flexibility.
    """

    event_type = serializers.CharField(
        max_length=50,
        help_text="Event category, e.g. status_changed, preview_captured, dispatched.",
    )
    payload = serializers.JSONField(
        required=False,
        help_text="Arbitrary structured payload. Shape varies by event_type.",
    )


class InternalDeploymentTransitionsViewSet(viewsets.ViewSet):
    """Internal endpoints called by the Temporal build worker.

    Authenticated via `X-Internal-Api-Secret` (constant-time compared
    against `settings.INTERNAL_API_SECRET`). No team context required
    on the URL — the deployment id resolves to a team via the row's
    `team_id` field (ProductTeamModel; reads bypass `objects` via
    `all_teams` because no team context is in scope).
    """

    authentication_classes = [InternalAPIAuthentication]

    def _get_deployment(self, deployment_id: str | UUID) -> Deployment:
        try:
            return Deployment.all_teams.get(pk=deployment_id)
        except Deployment.DoesNotExist as exc:
            raise NotFound(f"Deployment {deployment_id} not found.") from exc

    @extend_schema(exclude=True)
    def transitions(self, request: Request, deployment_id: str, *args: Any, **kwargs: Any) -> Response:
        body = InternalTransitionInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        target = Status(body.validated_data["status"])
        error_step_raw = body.validated_data.get("error_step")
        error_step = ErrorStep(error_step_raw) if error_step_raw else None

        # InternalAPIAuthentication does not set team context. Resolve the row
        # with `all_teams`, then enter scope so ModelActivityMixin and any
        # ProductTeamModel writes inside the transition use the deployment's
        # canonical team.
        deployment_for_scope = self._get_deployment(deployment_id)
        with team_scope(deployment_for_scope.team_id, canonical=True):
            try:
                deployment = update_status.execute(
                    update_status.UpdateStatusInput(
                        deployment_id=deployment_id,
                        status=target,
                        cloudflare_deployment_id=body.validated_data.get("cloudflare_deployment_id") or None,
                        deployment_url=body.validated_data.get("deployment_url") or None,
                        error_message=body.validated_data.get("error_message") or None,
                        error_step=error_step,
                        started_at=body.validated_data.get("started_at"),
                        finished_at=body.validated_data.get("finished_at"),
                    )
                )
            except Deployment.DoesNotExist as exc:
                raise NotFound(f"Deployment {deployment_id} not found.") from exc
            except InvalidStatusTransition as exc:
                logger.warning(
                    "internal_deployments.invalid_transition",
                    deployment_id=str(deployment_id),
                    current=str(exc.current),
                    target=str(exc.target),
                )
                return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)

            return Response(DeploymentSerializer(deployment).data, status=status.HTTP_200_OK)

    @extend_schema(exclude=True)
    def events(self, request: Request, deployment_id: str, *args: Any, **kwargs: Any) -> Response:
        deployment = self._get_deployment(deployment_id)

        body = InternalEventInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        with team_scope(deployment.team_id, canonical=True):
            event = DeploymentEvent.objects.create(
                deployment_id=deployment.pk,
                team_id=deployment.team_id,
                event_type=body.validated_data["event_type"],
                payload=body.validated_data.get("payload") or {},
            )
            return Response(
                {"id": str(event.id), "occurred_at": event.occurred_at.isoformat()},
                status=status.HTTP_202_ACCEPTED,
            )
