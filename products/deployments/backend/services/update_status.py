"""Apply a status transition to a Deployment.

The ONLY entry point that mutates `Deployment.status`. Called by the
internal `/api/internal/deployments/{id}/transitions/` endpoint when the
build worker posts a status update.

Invariants:
- SELECT FOR UPDATE on the row so concurrent transitions serialize.
- Idempotent: a duplicate `ready` callback on an already-`ready` row is
  a no-op (returns the existing instance). Detection uses
  `domain.status.is_idempotent_noop`.
- Side effects (annotation, ErrorTrackingRelease, $deployment event)
  scheduled via `transaction.on_commit` so a rolled-back transition
  leaves no orphan records.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from ..domain.status import Status, assert_valid, is_idempotent_noop
from ..domain.trigger import ErrorStep
from ..models import Deployment


@dataclass(frozen=True)
class UpdateStatusInput:
    deployment_id: UUID | str
    status: Status
    cloudflare_deployment_id: str | None = None
    deployment_url: str | None = None
    error_message: str | None = None
    error_step: ErrorStep | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


def execute(payload: UpdateStatusInput) -> Deployment:
    # Import here to avoid a circular import with finalize_success (which
    # depends on this module's UpdateStatusInput shape).
    from . import finalize_failure, finalize_success

    with transaction.atomic():
        deployment = (
            Deployment.all_teams.select_for_update(of=("self",)).select_related("project").get(pk=payload.deployment_id)
        )
        current = Status(deployment.status)
        target = payload.status

        if is_idempotent_noop(current, target):
            # Duplicate callback from a racing build activity. Don't error
            # — Temporal's at-least-once delivery makes this expected.
            return deployment

        assert_valid(current, target)

        deployment.status = target.value
        if payload.cloudflare_deployment_id is not None:
            deployment.cloudflare_deployment_id = payload.cloudflare_deployment_id
        if payload.deployment_url is not None:
            deployment.deployment_url = payload.deployment_url
        if payload.error_message is not None:
            deployment.error_message = payload.error_message
        if payload.error_step is not None:
            deployment.error_step = payload.error_step.value
        if payload.started_at is not None:
            deployment.started_at = payload.started_at
        if target == Status.INITIALIZING and deployment.started_at is None:
            deployment.started_at = timezone.now()
        if payload.finished_at is not None:
            deployment.finished_at = payload.finished_at
        if target in (Status.READY, Status.ERROR, Status.CANCELLED) and deployment.finished_at is None:
            deployment.finished_at = timezone.now()
        deployment.save(
            update_fields=[
                "status",
                "cloudflare_deployment_id",
                "deployment_url",
                "error_message",
                "error_step",
                "started_at",
                "finished_at",
            ]
        )

        # On READY, flip the project's current_deployment pointer atomically.
        if target == Status.READY:
            project = deployment.project
            project.current_deployment_id = deployment.pk
            project.save(update_fields=["current_deployment", "updated_at"])

        # Schedule side effects AFTER the commit. A rolled-back transition
        # (e.g. an exception during save) leaves no annotations, no
        # ErrorTrackingRelease, no $deployment events.
        if target == Status.READY:
            transaction.on_commit(lambda: finalize_success.execute(deployment_id=deployment.pk))
        elif target == Status.ERROR:
            transaction.on_commit(lambda: finalize_failure.execute(deployment_id=deployment.pk))

    return deployment
