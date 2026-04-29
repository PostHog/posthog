"""Create GitHub PRs from PostHog model changes.

When a user edits a GitHub-synced model in the PostHog UI, this service
creates a branch, commits the updated .sql file, and opens a PR.
The PR then triggers the plan/apply flow via webhooks.
"""

import re
from typing import Any
from uuid import uuid4

from django.core.exceptions import ObjectDoesNotExist

import structlog

from posthog.models.integration import GitHubIntegration

from products.data_modeling.backend.models import GitHubSyncConfig
from products.data_modeling.backend.services.github.sync_service import _extract_repo_name
from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

logger = structlog.get_logger(__name__)


def _sanitize_for_branch(name: str) -> str:
    """Sanitize a saved query name for use in a Git branch ref.

    Git refs disallow many characters that are valid in HogQL identifiers:
    spaces, '..', '~', '^', ':', '?', '*', '[', '\\', leading/trailing '-',
    leading '/', and a few more. Replace anything outside [A-Za-z0-9_-] with '-',
    collapse runs, and trim leading/trailing dashes.
    """
    sanitized = re.sub(r"[^A-Za-z0-9_-]+", "-", name)
    sanitized = re.sub(r"-+", "-", sanitized).strip("-")
    return sanitized or "model"


def create_pr_from_saved_query(
    saved_query: DataWarehouseSavedQuery,
    query_text: str,
) -> dict[str, Any]:
    """Create a GitHub PR with the updated model file.

    Looks up the GitHubSyncedModel to find the file path, serializes the
    query text back to a .sql file with annotations, creates a branch, commits
    the file, and opens a PR.

    Returns a dict with {success, pr_url, pr_number} on success,
    or {success: False, error} on failure.
    """
    if not query_text or not query_text.strip():
        return {"success": False, "error": "No query text provided"}

    try:
        synced_model = saved_query.github_synced_model
    except ObjectDoesNotExist:
        return {"success": False, "error": "Model is not synced from GitHub"}

    config = GitHubSyncConfig.objects.filter(team=saved_query.team).select_related("integration").first()
    if not config or not config.integration:
        return {"success": False, "error": "No GitHub sync configuration found"}

    github = GitHubIntegration(config.integration)
    repo_name = _extract_repo_name(config.repository)

    # query_text includes annotations (-- @mat, etc.) so write it directly
    file_content = query_text.rstrip() + "\n"

    # create branch — sanitize the model name so Git accepts the ref
    short_id = uuid4().hex[:8]
    safe_name = _sanitize_for_branch(saved_query.name)
    branch_name = f"posthog/update-{safe_name}-{short_id}"

    branch_result = github.create_branch(repo_name, branch_name)
    if not branch_result.get("success"):
        logger.warning(
            "create_pr_from_saved_query: failed to create branch",
            saved_query_id=str(saved_query.id),
            error=branch_result.get("error"),
        )
        return {"success": False, "error": branch_result.get("error", "Failed to create branch")}

    # commit the file update
    file_result = github.update_file(
        repo_name,
        synced_model.file_path,
        file_content,
        commit_message=f"Update {saved_query.name} from PostHog",
        branch=branch_name,
        sha=synced_model.file_sha,
    )
    if not file_result.get("success"):
        logger.warning(
            "create_pr_from_saved_query: failed to update file",
            saved_query_id=str(saved_query.id),
            error=file_result.get("error"),
        )
        return {"success": False, "error": file_result.get("error", "Failed to update file")}

    # open PR
    pr_result = github.create_pull_request(
        repo_name,
        title=f"Update {saved_query.name}",
        body=f"Model `{saved_query.name}` was updated in PostHog.\n\nFile: `{synced_model.file_path}`",
        head_branch=branch_name,
    )
    if not pr_result.get("success"):
        logger.warning(
            "create_pr_from_saved_query: failed to create PR",
            saved_query_id=str(saved_query.id),
            error=pr_result.get("error"),
        )
        return {"success": False, "error": pr_result.get("error", "Failed to create pull request")}

    logger.info(
        "create_pr_from_saved_query: PR created",
        saved_query_id=str(saved_query.id),
        pr_number=pr_result["pr_number"],
        pr_url=pr_result["pr_url"],
    )

    return {
        "success": True,
        "pr_url": pr_result["pr_url"],
        "pr_number": pr_result["pr_number"],
        "branch": branch_name,
    }
