"""Inbound GitHub App ``installation`` webhook handling.

This is the inbound side of bi-directional uninstall: when an account owner
uninstalls the App on GitHub, GitHub sends an ``installation`` event with
``action == "deleted"``. We then remove every PostHog row that referenced the
installation so we don't keep dead tokens around.

The handler never calls GitHub's DELETE endpoint — the App is already gone —
which keeps the outbound/inbound pair loop-free.

``action == "created"`` is the other direction: an org owner approved a pending install
request (see ``posthog.api.github_callback.install_requests``). The payload's ``requester.id``
is who asked, so matching pending ``GitHubInstallRequest`` rows on ``github_user_id`` flip to
approved, which is how the desktop learns the wait is over without polling GitHub itself.

The separate ``installation_repositories`` event fires when an owner changes which repositories
the App can see. It carries the new ``repository_selection`` ("all" or "selected"), which every
row for the installation mirrors so the UI can say "all repositories" instead of listing them.
"""

from typing import Any

from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone

import structlog

from posthog.integrations import IntegrationManager, IntegrationNotFound, IntegrationPatch
from posthog.models.integration import invalidate_github_repository_caches_for_installation
from posthog.models.integration.github_audit import GitHubAudit
from posthog.models.user_integration import GitHubInstallRequest, UserIntegration

logger = structlog.get_logger(__name__)


def handle_installation_event(payload: dict) -> HttpResponse:
    """Process a pre-verified GitHub ``installation`` webhook event.

    Registered by the GitHub incarnation as the ``installation_lifecycle`` consumer, so it
    runs after signature verification and JSON parsing. ``action == "deleted"`` triggers integration cleanup; ``"created"``
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

    github = IntegrationManager.github.oauth
    integrations = github.list_by_external_id(installation_id)

    project_audits = [GitHubAudit.project(row) for row in integrations]
    personal_rows = list(UserIntegration.objects.filter(kind="github", integration_id=installation_id))
    personal_audits = [GitHubAudit.personal(row) for row in personal_rows]
    deleted_audits: list[GitHubAudit] = []
    try:
        # A verified installation webhook removes this installation across projects. Delete the listed
        # rows by id, so the audit names exactly the rows that this request deleted, and all or none.
        with transaction.atomic():
            for row, audit in zip(integrations, project_audits):
                try:
                    github.delete(row.team_id, row.id, ignore_usages=True)
                except IntegrationNotFound:
                    continue
                deleted_audits.append(audit)
    except Exception as exc:
        for audit in project_audits:
            audit.record("webhook_cleanup_failed", stage="project_deletion", failure_type=type(exc).__name__)
        raise
    team_deleted = len(deleted_audits)
    for audit in deleted_audits:
        audit.record("deleted", after_commit=True, customer_visible=True, outcome="disconnected")
        audit.record("webhook_cleanup", after_commit=True, outcome="already_absent", completed_deletion=True)
    try:
        user_deleted, _ = UserIntegration.objects.filter(pk__in=[row.pk for row in personal_rows]).delete()
    except Exception as exc:
        for audit in personal_audits:
            audit.record("webhook_cleanup_failed", stage="personal_deletion", failure_type=type(exc).__name__)
        raise
    for audit in personal_audits:
        audit.record("credential_deleted", after_commit=True, reason="installation_deleted_webhook")

    logger.info(
        "github_installation_webhook_uninstalled",
        installation_id=installation_id,
        team_integrations_deleted=team_deleted,
        user_integrations_deleted=user_deleted,
    )

    return HttpResponse(status=200)


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
    team_updated = IntegrationManager.github.oauth.update_by_external_id(
        installation_id, IntegrationPatch(config_patch={"repository_selection": repository_selection})
    )
    # For the personal rows, load only the columns we touch. The encrypted sensitive_config
    # (decrypted eagerly on load) is skipped so a widely shared installation can't spike a web
    # worker's memory here. Like the SDK call above, the write is one bulk_update of the changed rows.
    user_changed = [
        row
        for row in UserIntegration.objects.filter(kind="github", integration_id=installation_id).only("id", "config")
        if row.config.get("repository_selection") != repository_selection
    ]
    for row in user_changed:
        row.config = {**row.config, "repository_selection": repository_selection}
    if user_changed:
        UserIntegration.objects.bulk_update(user_changed, ["config"])
    updated = team_updated + len(user_changed)

    invalidate_github_repository_caches_for_installation(installation_id)

    logger.info(
        "github_installation_repositories_webhook_applied",
        installation_id=installation_id,
        repository_selection=repository_selection,
        rows_updated=updated,
    )
    return HttpResponse(status=200)
