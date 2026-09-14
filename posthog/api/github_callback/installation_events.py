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

``action == "created"`` is the other direction: an org owner approved a pending install
request (see ``posthog.api.github_callback.install_requests``). The payload's ``requester.id``
is who asked, so matching pending ``GitHubInstallRequest`` rows on ``github_user_id`` flip to
approved, which is how the desktop learns the wait is over without polling GitHub itself.

The separate ``installation_repositories`` event fires when an owner changes which repositories
the App can see. It carries the new ``repository_selection`` ("all" or "selected"), which every
row for the installation mirrors so the UI can say "all repositories" instead of listing them.
"""

from typing import Any

from django.http import HttpResponse
from django.utils import timezone

import structlog

from posthog.models.integration import Integration, invalidate_github_repository_caches_for_installation
from posthog.models.user_integration import GitHubInstallRequest, UserIntegration

logger = structlog.get_logger(__name__)


def handle_installation_event(payload: dict) -> HttpResponse:
    """Process a pre-verified GitHub ``installation`` webhook event.

    Called from ``posthog.urls.github_webhook`` after signature verification and
    JSON parsing. ``action == "deleted"`` triggers integration cleanup; ``"created"``
    resolves matching pending install requests. Reversible actions (suspend/unsuspend)
    and other lifecycle noise are ignored.
    """
    action = payload.get("action")
    if action == "created":
        return _handle_installation_created(payload)
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


def _handle_installation_created(payload: dict) -> HttpResponse:
    installation_id = (payload.get("installation") or {}).get("id")
    requester_id = (payload.get("requester") or {}).get("id")
    if installation_id is None or requester_id is None:
        # An owner installing for themselves has no requester, so this is the common case.
        logger.debug(
            "github_installation_webhook_created_no_requester",
            installation_id=installation_id,
            has_requester=requester_id is not None,
        )
        return HttpResponse(status=200)

    account = (payload.get("installation") or {}).get("account") or {}
    update_fields: dict[str, Any] = {
        "status": GitHubInstallRequest.Status.APPROVED,
        "installation_id": str(installation_id),
        "resolved_at": timezone.now(),
    }
    if account.get("login"):
        update_fields["account_login"] = str(account["login"])[:255]
    if account.get("type"):
        update_fields["account_type"] = str(account["type"])[:32]

    resolved_count = GitHubInstallRequest.objects.filter(
        github_user_id=requester_id, status=GitHubInstallRequest.Status.PENDING
    ).update(**update_fields)

    logger.info(
        "github_installation_webhook_created",
        installation_id=str(installation_id),
        requester_id=requester_id,
        resolved_count=resolved_count,
    )

    return HttpResponse(status=200)


def handle_installation_repositories_event(payload: dict) -> HttpResponse:
    """Mirror a changed ``repository_selection`` onto every row for the installation and drop
    their repository caches so the next list reflects the new access."""
    installation_id = (payload.get("installation") or {}).get("id")
    repository_selection = payload.get("repository_selection")
    if installation_id is None or not isinstance(repository_selection, str):
        logger.warning(
            "github_installation_repositories_webhook_missing_fields",
            has_installation_id=installation_id is not None,
            repository_selection=repository_selection,
        )
        return HttpResponse(status=200)

    installation_id = str(installation_id)
    # Load only the columns we touch. The unbounded repository_cache blob and the encrypted
    # sensitive_config (decrypted eagerly on load) are skipped so a widely shared installation
    # can't spike a web worker's memory here. Writes go out as one bulk_update per model instead
    # of a save per row — which also skips the (no-op for github) push-config post_save signal,
    # avoiding a per-row lazy load of the deferred `kind`.
    team_changed = [
        row
        for row in Integration.objects.filter(kind="github", integration_id=installation_id).only("id", "config")
        if row.config.get("repository_selection") != repository_selection
    ]
    user_changed = [
        row
        for row in UserIntegration.objects.filter(kind="github", integration_id=installation_id).only("id", "config")
        if row.config.get("repository_selection") != repository_selection
    ]
    changed: list[Integration | UserIntegration] = [*team_changed, *user_changed]
    for row in changed:
        row.config = {**row.config, "repository_selection": repository_selection}
    if team_changed:
        Integration.objects.bulk_update(team_changed, ["config"])
    if user_changed:
        UserIntegration.objects.bulk_update(user_changed, ["config"])
    updated = len(changed)

    invalidate_github_repository_caches_for_installation(installation_id)

    logger.info(
        "github_installation_repositories_webhook_applied",
        installation_id=installation_id,
        repository_selection=repository_selection,
        rows_updated=updated,
    )
    return HttpResponse(status=200)
