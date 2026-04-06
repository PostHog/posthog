"""Create GitHub PRs from PostHog model changes.

When a user edits a GitHub-synced model in the PostHog UI, this service
creates a branch, commits the updated .sql file, and opens a PR.
The PR then triggers the plan/apply flow via webhooks.
"""

from typing import Any
from uuid import uuid4

import structlog

from posthog.models.integration import GitHubIntegration

from products.data_modeling.backend.models import GitHubSyncConfig
from products.data_modeling.backend.services.github.model_parser import serialize_model_file
from products.data_modeling.backend.services.github.sync_service import _extract_repo_name
from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

logger = structlog.get_logger(__name__)


def create_pr_from_saved_query(saved_query: DataWarehouseSavedQuery) -> dict[str, Any]:
    """Create a GitHub PR with the updated model file.

    Looks up the GitHubSyncedModel to find the file path, serializes the
    current query back to SQL with annotations, creates a branch, commits
    the file, and opens a PR.

    Returns a dict with {success, pr_url, pr_number} on success,
    or {success: False, error} on failure.
    """
    try:
        synced_model = saved_query.github_synced_model
    except Exception:
        return {"success": False, "error": "Model is not synced from GitHub"}

    config = GitHubSyncConfig.objects.filter(team=saved_query.team).select_related("integration").first()
    if not config or not config.integration:
        return {"success": False, "error": "No GitHub sync configuration found"}

    github = GitHubIntegration(config.integration)
    repo_name = _extract_repo_name(config.repository)

    # serialize the current state back to .sql
    query_text = saved_query.query.get("query", "") if saved_query.query else ""
    if not query_text:
        return {"success": False, "error": "Saved query has no query text"}

    # determine materialization from the node type
    from products.data_modeling.backend.models.node import Node, NodeType

    is_materialized = Node.objects.filter(
        saved_query=saved_query,
        type=NodeType.MAT_VIEW,
    ).exists()

    file_content = serialize_model_file(
        query_text,
        materialized=is_materialized,
    )

    # create branch
    short_id = uuid4().hex[:8]
    branch_name = f"posthog/update-{saved_query.name}-{short_id}"

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
