"""GitHub webhook handler for ci_monitoring."""

from __future__ import annotations

import json

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

import structlog

from products.tasks.backend.webhooks import get_github_webhook_secret, verify_github_signature

from .. import logic
from ..facade.enums import CIRunConclusion

logger = structlog.get_logger(__name__)

# Map GitHub conclusion strings to our enum
_CONCLUSION_MAP: dict[str, CIRunConclusion] = {
    "success": CIRunConclusion.SUCCESS,
    "failure": CIRunConclusion.FAILURE,
    "cancelled": CIRunConclusion.CANCELLED,
    "timed_out": CIRunConclusion.TIMED_OUT,
}


@csrf_exempt
def github_workflow_run_webhook(request: HttpRequest) -> HttpResponse:
    """
    Handle GitHub workflow_run webhook events.

    Receives workflow_run.completed events, creates a CIRun record,
    and dispatches artifact ingestion.
    """
    if request.method != "POST":
        return HttpResponse(status=405)

    webhook_secret = get_github_webhook_secret()
    if not webhook_secret:
        logger.error("ci_monitoring.webhook_no_secret")
        return HttpResponse("Webhook not configured", status=500)

    signature = request.headers.get("X-Hub-Signature-256")
    if not verify_github_signature(request.body, signature, webhook_secret):
        logger.warning("ci_monitoring.webhook_invalid_signature", has_signature=bool(signature))
        return HttpResponse("Invalid signature", status=403)

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON", status=400)

    event_type = request.headers.get("X-GitHub-Event")
    if event_type != "workflow_run":
        return HttpResponse(status=200)

    action = payload.get("action")
    if action != "completed":
        return HttpResponse(status=200)

    workflow_run = payload.get("workflow_run", {})
    repository = payload.get("repository", {})

    conclusion_str = workflow_run.get("conclusion", "")
    conclusion = _CONCLUSION_MAP.get(conclusion_str)
    if conclusion is None:
        logger.debug("ci_monitoring.webhook_ignored_conclusion", conclusion=conclusion_str)
        return HttpResponse(status=200)

    pr_number = None
    pull_requests = workflow_run.get("pull_requests", [])
    if pull_requests:
        pr_number = pull_requests[0].get("number")

    repo_external_id = repository.get("id")
    repo_full_name = repository.get("full_name")
    if not repo_external_id or not repo_full_name:
        logger.warning("ci_monitoring.webhook_missing_repo_info")
        return HttpResponse(status=200)

    try:
        ci_run = logic.create_ci_run_from_webhook(
            repo_external_id=repo_external_id,
            repo_full_name=repo_full_name,
            github_run_id=workflow_run.get("id"),
            workflow_name=workflow_run.get("name", ""),
            commit_sha=workflow_run.get("head_sha", ""),
            branch=workflow_run.get("head_branch", ""),
            conclusion=conclusion,
            started_at=workflow_run.get("run_started_at"),
            completed_at=workflow_run.get("updated_at"),
            pr_number=pr_number,
        )
    except logic.RepoNotFoundError:
        logger.debug(
            "ci_monitoring.webhook_repo_not_found",
            repo_external_id=repo_external_id,
            repo_full_name=repo_full_name,
        )
        return HttpResponse(status=200)

    from ..tasks.tasks import ingest_ci_run_artifacts

    ingest_ci_run_artifacts.delay(ci_run_id=str(ci_run.id))

    logger.info(
        "ci_monitoring.webhook_processed",
        ci_run_id=str(ci_run.id),
        workflow=ci_run.workflow_name,
        conclusion=conclusion_str,
    )

    return HttpResponse(status=200)
