"""Side effects scheduled when a Deployment flips to ERROR.

Emits a `$exception` PostHog event so the failure shows up in Error
Tracking grouped by deployment_id. The `$exception_releases` property
matches the shape Error Tracking already stores (see
products/error_tracking/backend/api/query_utils.py).
"""

from __future__ import annotations

from uuid import UUID

import structlog

from posthog.ph_client import ph_scoped_capture

from ..models import Deployment

logger = structlog.get_logger(__name__)


def execute(*, deployment_id: UUID | str) -> None:
    deployment = Deployment.all_teams.select_related("project").filter(pk=deployment_id).first()
    if deployment is None:
        logger.warning("finalize_failure.missing_deployment", deployment_id=str(deployment_id))
        return

    distinct_id = (
        str(deployment.triggered_by_user_id)
        if deployment.triggered_by_user_id is not None
        else f"team_{deployment.team_id}"
    )

    sha7 = deployment.commit_sha[:7] if deployment.commit_sha else str(deployment.id)[:7]

    with ph_scoped_capture() as capture:
        capture(
            distinct_id=distinct_id,
            event="$exception",
            properties={
                "$exception_type": "DeploymentBuildFailed",
                "$exception_message": deployment.error_message or f"Build failed at step {deployment.error_step}",
                "$exception_releases": {sha7: deployment.deployment_url or None},
                "deployment_id": str(deployment.id),
                "project_id": str(deployment.project_id),
                "error_step": deployment.error_step,
                "commit_sha": deployment.commit_sha,
                "repo_url": deployment.repo_url,
                "branch": deployment.branch,
                "trigger_kind": deployment.trigger_kind,
            },
            groups={"project": str(deployment.team_id)},
        )
