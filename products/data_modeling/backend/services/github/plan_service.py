"""Plan computation and rendering for GitHub PR-based data modeling changes.

Computes a structural diff of what a PR would change when merged:
which models and DAGs would be added, modified, removed, or renamed.
Renders the plan as a GitHub-flavored markdown comment and posts it to the PR.
"""

from typing import TYPE_CHECKING, Any

import structlog

from posthog.models.integration import GitHubIntegration

from products.data_modeling.backend.models import GitHubSyncConfig, GitHubSyncPlan, GitHubSyncPlanStatus
from products.data_modeling.backend.services.github.config_parser import DAG_TOML
from products.data_modeling.backend.services.github.model_parser import model_name_from_path
from products.data_modeling.backend.services.github.sync_service import _extract_repo_name

if TYPE_CHECKING:
    from posthog.models import Team

logger = structlog.get_logger(__name__)

PLAN_COMMENT_HEADER = "<!-- posthog-data-modeling-plan -->"


def compute_plan(
    *,
    team: "Team",
    config: GitHubSyncConfig,
    pr_number: int,
    pr_url: str,
    head_sha: str,
) -> GitHubSyncPlan | None:
    """Compute a structural diff plan from a PR's changed files.

    Fetches the list of changed files from GitHub, filters for model (.sql)
    and DAG (dag.toml) files, and classifies each change. Does not parse SQL
    or validate queries — this is a structural preview only.

    Returns the created GitHubSyncPlan, or None if the GitHub API call fails.
    """
    if not config.integration:
        logger.warning("compute_plan: no integration configured", team_id=team.id)
        return None

    github = GitHubIntegration(config.integration)
    repo_name = _extract_repo_name(config.repository)
    result = github.get_pull_request_files(repo_name, pr_number)

    if not result.get("success"):
        logger.warning(
            "compute_plan: failed to fetch PR files",
            team_id=team.id,
            pr_number=pr_number,
            error=result.get("error"),
        )
        return None

    models_dir = config.models_directory or "models"
    env_name = config.environment_name
    plan_data = _classify_changes(result["files"], models_dir, env_name)

    # mark previous pending plans for this PR as stale
    GitHubSyncPlan.objects.filter(
        team=team,
        config=config,
        pr_number=pr_number,
        status=GitHubSyncPlanStatus.PENDING,
    ).update(status=GitHubSyncPlanStatus.STALE)

    plan = GitHubSyncPlan.objects.create(
        team=team,
        config=config,
        pr_number=pr_number,
        pr_url=pr_url,
        head_sha=head_sha,
        plan=plan_data,
    )

    logger.info(
        "compute_plan: plan created",
        team_id=team.id,
        pr_number=pr_number,
        plan_id=str(plan.id),
        model_changes=sum(len(v) for v in plan_data.get("models", {}).values()),
        dag_changes=sum(len(v) for v in plan_data.get("dags", {}).values()),
    )
    return plan


def _classify_changes(
    files: list[dict[str, Any]],
    models_dir: str,
    env_name: str,
) -> dict[str, Any]:
    """Classify PR file changes into model and DAG operations.

    Filters for files under the models directory (respecting multi-env layout)
    and groups them by type (model .sql vs dag.toml) and operation.
    """
    # determine the base prefix — we can't check for multi-env without the full tree,
    # so we infer from the changed files themselves
    multi_env_prefix = f"{models_dir}/{env_name}/"
    single_env_prefix = f"{models_dir}/"
    has_env_dir = any(f["filename"].startswith(multi_env_prefix) for f in files)
    base_prefix = multi_env_prefix if has_env_dir else single_env_prefix

    models: dict[str, list[dict[str, str]]] = {"added": [], "modified": [], "removed": [], "renamed": []}
    dags: dict[str, list[dict[str, Any]]] = {"added": [], "modified": [], "removed": []}

    for f in files:
        filename = f["filename"]
        status = f["status"]
        previous_filename = f.get("previous_filename", "")

        # check if the file (or its previous name for renames) is under the models dir
        is_relevant = filename.startswith(base_prefix)
        if not is_relevant and status == "renamed":
            is_relevant = previous_filename.startswith(base_prefix)
        if not is_relevant:
            continue

        if filename.endswith(DAG_TOML) or (status == "removed" and previous_filename.endswith(DAG_TOML)):
            _classify_dag_change(f, status, dags)
        elif filename.endswith(".sql") or (status == "removed" and previous_filename.endswith(".sql")):
            _classify_model_change(f, status, models)

    return {"models": models, "dags": dags}


def _classify_model_change(
    f: dict[str, Any],
    status: str,
    models: dict[str, list[dict[str, str]]],
) -> None:
    filename = f["filename"]
    previous_filename = f.get("previous_filename", "")

    if status == "added":
        models["added"].append(
            {
                "path": filename,
                "name": model_name_from_path(filename),
            }
        )
    elif status == "modified":
        models["modified"].append(
            {
                "path": filename,
                "name": model_name_from_path(filename),
            }
        )
    elif status == "removed":
        models["removed"].append(
            {
                "path": filename,
                "name": model_name_from_path(filename),
            }
        )
    elif status == "renamed":
        models["renamed"].append(
            {
                "old_path": previous_filename,
                "new_path": filename,
                "name": model_name_from_path(filename),
            }
        )


def _classify_dag_change(
    f: dict[str, Any],
    status: str,
    dags: dict[str, list[dict[str, Any]]],
) -> None:
    filename = f["filename"]

    if status == "added":
        dags["added"].append({"path": filename})
    elif status == "modified":
        dags["modified"].append({"path": filename})
    elif status == "removed":
        dags["removed"].append({"path": filename})


# ---------------------------------------------------------------------------
# Rendering + posting
# ---------------------------------------------------------------------------


def render_plan_comment(plan: GitHubSyncPlan) -> str:
    """Render a plan as markdown suitable for a GitHub PR comment."""
    plan_data = plan.plan
    models = plan_data.get("models", {})
    dags = plan_data.get("dags", {})

    model_count = sum(len(v) for v in models.values())
    dag_count = sum(len(v) for v in dags.values())
    total = model_count + dag_count

    lines: list[str] = [PLAN_COMMENT_HEADER, "", "### PostHog data modeling plan", ""]

    if total == 0:
        lines.append("No data modeling changes detected in this PR.")
        return "\n".join(lines)

    change_word = "change" if total == 1 else "changes"
    lines.append(f"**{total} {change_word}** detected in this PR.")
    lines.append("")

    if model_count > 0:
        lines.append("#### Models")
        lines.append("| Action | Model | Path |")
        lines.append("|--------|-------|------|")
        for m in models.get("added", []):
            lines.append(f"| + Add | `{m['name']}` | `{m['path']}` |")
        for m in models.get("modified", []):
            lines.append(f"| ~ Modify | `{m['name']}` | `{m['path']}` |")
        for m in models.get("renamed", []):
            lines.append(f"| → Rename | `{m['name']}` | `{m.get('old_path', '')}` → `{m['new_path']}` |")
        for m in models.get("removed", []):
            lines.append(f"| - Remove | `{m['name']}` | `{m['path']}` |")
        lines.append("")

    if dag_count > 0:
        lines.append("#### DAGs")
        lines.append("| Action | Path |")
        lines.append("|--------|------|")
        for d in dags.get("added", []):
            lines.append(f"| + Add | `{d['path']}` |")
        for d in dags.get("modified", []):
            lines.append(f"| ~ Modify | `{d['path']}` |")
        for d in dags.get("removed", []):
            lines.append(f"| - Remove | `{d['path']}` |")
        lines.append("")

    lines.append("> This plan will be applied when the PR is merged.")
    return "\n".join(lines)


def post_plan_comment(plan: GitHubSyncPlan, config: GitHubSyncConfig) -> None:
    """Render the plan and post or update the PR comment."""
    if not config.integration:
        return

    body = render_plan_comment(plan)
    github = GitHubIntegration(config.integration)
    repo_name = _extract_repo_name(config.repository)

    # try to reuse an existing comment ID from this or a previous (stale) plan on the same PR
    existing_comment_id = plan.github_comment_id
    if existing_comment_id is None:
        previous = (
            GitHubSyncPlan.objects.filter(
                config=config,
                pr_number=plan.pr_number,
                github_comment_id__isnull=False,
            )
            .exclude(id=plan.id)
            .order_by("-created_at")
            .values_list("github_comment_id", flat=True)
            .first()
        )
        if previous is not None:
            existing_comment_id = previous

    result = github.create_or_update_issue_comment(
        repo_name,
        plan.pr_number,
        body,
        comment_id=existing_comment_id,
    )

    if result.get("success"):
        plan.github_comment_id = result["comment_id"]
        plan.save(update_fields=["github_comment_id"])
    else:
        logger.warning(
            "post_plan_comment: failed to post comment",
            plan_id=str(plan.id),
            pr_number=plan.pr_number,
            error=result.get("error"),
        )
