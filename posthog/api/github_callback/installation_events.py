"""Inbound GitHub App ``installation`` webhook handling.

This is the inbound side of bi-directional uninstall: when an account owner
uninstalls the App on GitHub, GitHub sends an ``installation`` event with
``action == "deleted"``. We then remove every PostHog row that referenced the
installation so we don't keep dead tokens around.

The handler never calls GitHub's DELETE endpoint — the App is already gone —
which keeps the outbound/inbound pair loop-free.

Before the Integration rows are deleted, any Loop (products/tasks) referencing them is
auto-paused and flagged for attention, so a disconnected integration never leaves a loop
silently pointed at a repository it can no longer reach.
"""

from django.http import HttpResponse

import structlog

from posthog.models.integration import Integration
from posthog.models.user_integration import UserIntegration

logger = structlog.get_logger(__name__)


def handle_installation_event(payload: dict) -> HttpResponse:
    """Process a pre-verified GitHub ``installation`` webhook event.

    Called from ``posthog.urls.github_webhook`` after signature verification and
    JSON parsing. Only ``action == "deleted"`` triggers cleanup; reversible
    actions (suspend/unsuspend) and lifecycle noise (created, etc.) are ignored.
    """
    action = payload.get("action")
    if action != "deleted":
        logger.debug("github_installation_webhook_ignored_action", action=action)
        return HttpResponse(status=200)

    installation_id = (payload.get("installation") or {}).get("id")
    if installation_id is None:
        logger.warning("github_installation_webhook_missing_installation_id", action=action)
        return HttpResponse(status=200)

    installation_id = str(installation_id)

    integrations = list(Integration.objects.filter(kind="github", integration_id=installation_id))
    _pause_loops_referencing_integrations(integrations, installation_id)

    team_deleted, _ = Integration.objects.filter(kind="github", integration_id=installation_id).delete()
    user_deleted, _ = UserIntegration.objects.filter(kind="github", integration_id=installation_id).delete()

    logger.info(
        "github_installation_webhook_uninstalled",
        installation_id=installation_id,
        team_integrations_deleted=team_deleted,
        user_integrations_deleted=user_deleted,
    )

    return HttpResponse(status=200)


def _pause_loops_referencing_integrations(integrations: list[Integration], installation_id: str) -> None:
    """Auto-pause every loop referencing a GitHub integration that's about to be hard-deleted.

    See products/tasks/docs/LOOPS.md "Lifecycle and reconciliation": the App uninstall hard-deletes
    the Integration row with no downstream hooks, and loop references to it are JSON, so no FK
    machinery helps. Runs before the delete below and is fully isolated: a loops-side failure must
    never break the pre-existing Integration/UserIntegration deletion path.
    """
    if not integrations:
        return

    try:
        from products.tasks.backend.facade.loops import (  # noqa: PLC0415 (keeps the loops/Temporal dependency off this module's import path)
            pause_loops_referencing_integrations,
        )
    except Exception:
        logger.exception("github_installation_webhook_loop_import_failed", installation_id=installation_id)
        return

    pause_loops_referencing_integrations(integrations, installation_id)
