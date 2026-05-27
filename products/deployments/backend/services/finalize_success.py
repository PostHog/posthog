"""Side effects scheduled when a Deployment flips to READY.

This is OUR responsibility — not Build/Infra's. It runs the actual Posthog-
internal integrations (Annotation, ErrorTrackingRelease, $deployment event)
that close the loop between deploys and the rest of the product.

Called via `transaction.on_commit(lambda: execute(...))` from update_status
so a rolled-back transition leaves nothing behind. The callback fires
AFTER the request transaction commits — at that point the request's team
scope (set by `TeamAndOrgViewSetMixin`) has already been torn down, and
the internal endpoint never sets one in the first place. We re-enter
team scope from `deployment.team_id` so the TeamScopedManager finds rows.
"""

from __future__ import annotations

from uuid import UUID

from django.utils import timezone

import structlog

from posthog.models.scoping import team_scope
from posthog.models.team.team import Team
from posthog.ph_client import ph_scoped_capture

from products.annotations.backend.models.annotation import Annotation
from products.error_tracking.backend.models import ErrorTrackingRelease

from ..adapters import ScreenshotAdapter, get_screenshot_adapter
from ..models import Deployment, DeploymentEvent

logger = structlog.get_logger(__name__)


def execute(*, deployment_id: UUID | str, screenshot: ScreenshotAdapter | None = None) -> None:
    # `all_teams` bypasses TeamScopedManager so we can read the row before
    # entering scope. Once we have `team_id` from the row, we enter scope
    # for the rest of the work so subsequent writes to scoped models
    # (Deployment, DeploymentEvent) succeed.
    deployment = Deployment.all_teams.select_related("project").filter(pk=deployment_id).first()
    if deployment is None:
        # Row was deleted between commit and callback. Drop quietly.
        logger.warning("finalize_success.missing_deployment", deployment_id=str(deployment_id))
        return

    with team_scope(deployment.team_id, canonical=True):
        # 1) Annotation marking the deploy on insight timelines.
        _create_annotation(deployment)

        # 2) ErrorTrackingRelease — join key the UI uses to link runtime
        #    exceptions back to the deploy that introduced them.
        _create_error_tracking_release(deployment)

        # 3) $deployment PostHog event for downstream funnels / webhooks.
        _emit_deployment_event(deployment)

        # 4) Best-effort preview screenshot. Failure surfaces as a
        #    preview_capture_failed event but does NOT roll back ready.
        #    Guard the empty-URL case explicitly with a distinct payload
        #    `reason` — otherwise the event log would record a spurious
        #    "failure" for a capture that was never attempted. Matches
        #    the shape used by `refresh_preview.execute`.
        if not deployment.deployment_url:
            DeploymentEvent.objects.create(
                deployment_id=deployment.pk,
                team_id=deployment.team_id,
                event_type="preview_capture_failed",
                payload={"reason": "no_deployment_url"},
            )
        else:
            screenshot_adapter = screenshot or get_screenshot_adapter()
            image_url = screenshot_adapter.capture(url=deployment.deployment_url)
            if image_url:
                Deployment.objects.filter(pk=deployment.pk).update(preview_image_url=image_url)
                DeploymentEvent.objects.create(
                    deployment_id=deployment.pk,
                    team_id=deployment.team_id,
                    event_type="preview_captured",
                    payload={"url": image_url},
                )
            else:
                DeploymentEvent.objects.create(
                    deployment_id=deployment.pk,
                    team_id=deployment.team_id,
                    event_type="preview_capture_failed",
                    payload={"deployment_url": deployment.deployment_url},
                )


def _create_annotation(deployment: Deployment) -> None:
    """Create a PROJECT-scoped annotation with creation_type=GIT."""
    organization_id = Team.objects.filter(id=deployment.team_id).values_list("organization_id", flat=True).first()
    if organization_id is None:
        # The team has been deleted between the build starting and ready.
        logger.warning("finalize_success.no_organization", team_id=deployment.team_id)
        return
    content = _annotation_content(deployment)
    Annotation.objects.create(
        team_id=deployment.team_id,
        organization_id=organization_id,
        scope=Annotation.Scope.PROJECT,
        creation_type=Annotation.CreationType.GITHUB,
        date_marker=deployment.finished_at or timezone.now(),
        content=content,
    )


def _annotation_content(deployment: Deployment) -> str:
    sha7 = deployment.commit_sha[:7] if deployment.commit_sha else ""
    msg = (deployment.commit_message or "").splitlines()[0] if deployment.commit_message else ""
    msg = msg[:80]
    if msg and sha7:
        return f"{msg} ({sha7})"
    if sha7:
        return f"Deploy {sha7}"
    return f"Deploy {deployment.id}"


def _create_error_tracking_release(deployment: Deployment) -> None:
    """Idempotent — the (team_id, hash_id) unique constraint silently
    de-dupes repeated calls."""
    try:
        ErrorTrackingRelease.objects.get_or_create(
            team_id=deployment.team_id,
            hash_id=str(deployment.id),
            defaults={
                "version": deployment.commit_sha[:7] if deployment.commit_sha else str(deployment.id)[:7],
                "project": deployment.project.cloudflare_project_name or deployment.project.slug,
                "metadata": {
                    "deployment_id": str(deployment.id),
                    "commit_sha": deployment.commit_sha,
                    "commit_message": deployment.commit_message,
                    "deployment_url": deployment.deployment_url,
                    "branch": deployment.branch,
                },
            },
        )
    except Exception as exc:  # noqa: BLE001 — finalize_success is best-effort
        # Don't let a release-row failure block the deployment from being
        # marked ready. Log and move on.
        logger.exception("finalize_success.error_tracking_release_failed", error=str(exc))


def _emit_deployment_event(deployment: Deployment) -> None:
    """Emit $deployment via ph_scoped_capture — Temporal/Celery-safe."""
    distinct_id = (
        str(deployment.triggered_by_user_id)
        if deployment.triggered_by_user_id is not None
        else f"team_{deployment.team_id}"
    )
    duration_seconds: int | None = None
    if deployment.finished_at and deployment.started_at:
        duration_seconds = int((deployment.finished_at - deployment.started_at).total_seconds())

    with ph_scoped_capture() as capture:
        capture(
            distinct_id=distinct_id,
            event="$deployment",
            properties={
                "deployment_id": str(deployment.id),
                "project_id": str(deployment.project_id),
                "commit_sha": deployment.commit_sha,
                "commit_message": deployment.commit_message,
                "branch": deployment.branch,
                "deployment_url": deployment.deployment_url,
                "subdomain": deployment.project.subdomain,
                "framework": deployment.project.framework,
                "trigger_kind": deployment.trigger_kind,
                "duration_seconds": duration_seconds,
            },
            groups={"project": str(deployment.team_id)},
        )
