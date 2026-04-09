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
    is_multi_env = GitHubSyncConfig.objects.filter(repository=config.repository).count() > 1
    plan_data = _classify_changes(result["files"], models_dir, env_name, is_multi_env=is_multi_env)

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
    is_multi_env: bool = False,
) -> dict[str, Any]:
    """Classify PR file changes into model and DAG operations.

    Filters for files under the models directory (respecting multi-env layout)
    and groups them by type (model .sql vs dag.toml) and operation.
    """
    if is_multi_env:
        base_prefix = f"{models_dir}/{env_name}/"
    else:
        base_prefix = f"{models_dir}/"

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


def _render_plan_section(plan_data: dict[str, Any]) -> list[str]:
    """Render model and DAG tables for a single plan. Returns lines without header/footer."""
    models = plan_data.get("models", {})
    dags = plan_data.get("dags", {})
    lines: list[str] = []

    model_count = sum(len(v) for v in models.values())
    if model_count > 0:
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

    dag_count = sum(len(v) for v in dags.values())
    if dag_count > 0:
        if model_count > 0:
            lines.append("**DAGs**")
            lines.append("")
        lines.append("| Action | Path |")
        lines.append("|--------|------|")
        for d in dags.get("added", []):
            lines.append(f"| + Add | `{d['path']}` |")
        for d in dags.get("modified", []):
            lines.append(f"| ~ Modify | `{d['path']}` |")
        for d in dags.get("removed", []):
            lines.append(f"| - Remove | `{d['path']}` |")
        lines.append("")

    return lines


def render_plan_comment(plan: GitHubSyncPlan) -> str:
    """Render a single plan as markdown. Used when there's only one environment."""
    plan_data = plan.plan
    total = sum(len(v) for v in plan_data.get("models", {}).values()) + sum(
        len(v) for v in plan_data.get("dags", {}).values()
    )

    lines: list[str] = [PLAN_COMMENT_HEADER, "", "### PostHog data modeling plan", ""]

    if total == 0:
        lines.append("No data modeling changes detected in this PR.")
        return "\n".join(lines)

    change_word = "change" if total == 1 else "changes"
    lines.append(f"**{total} {change_word}** detected in this PR.")
    lines.append("")
    lines.extend(_render_plan_section(plan_data))
    lines.append("> This plan will be applied when the PR is merged.")
    return "\n".join(lines)


def render_combined_plan_comment(plans: list[tuple[str, GitHubSyncPlan]]) -> str:
    """Render multiple plans (one per environment) into a single comment.

    Args:
        plans: list of (environment_name, plan) tuples
    """
    lines: list[str] = [PLAN_COMMENT_HEADER, "", "### PostHog data modeling plan", ""]

    total = 0
    for _, plan in plans:
        plan_data = plan.plan
        total += sum(len(v) for v in plan_data.get("models", {}).values())
        total += sum(len(v) for v in plan_data.get("dags", {}).values())

    if total == 0:
        lines.append("No data modeling changes detected in this PR.")
        return "\n".join(lines)

    change_word = "change" if total == 1 else "changes"
    lines.append(f"**{total} {change_word}** detected in this PR.")
    lines.append("")

    for env_name, plan in plans:
        section = _render_plan_section(plan.plan)
        if section:
            lines.append(f"#### {env_name}")
            lines.append("")
            lines.extend(section)

    lines.append("> This plan will be applied when the PR is merged.")
    return "\n".join(lines)


def post_plan_comment(
    plans: list[tuple[str, GitHubSyncPlan]],
    configs: list[GitHubSyncConfig],
    pr_number: int,
) -> None:
    """Render plans and post or update a single PR comment.

    Args:
        plans: list of (environment_name, plan) tuples
        configs: all configs for this repo (used to find integration and previous comment IDs)
        pr_number: the PR number to post on
    """
    # find a config with a working integration
    config = next((c for c in configs if c.integration), None)
    if not config:
        return

    if len(plans) == 1:
        body = render_plan_comment(plans[0][1])
    else:
        body = render_combined_plan_comment(plans)

    github = GitHubIntegration(config.integration)
    repo_name = _extract_repo_name(config.repository)

    # try to reuse an existing comment ID from any plan on this PR
    existing_comment_id = (
        GitHubSyncPlan.objects.filter(
            config__repository=config.repository,
            pr_number=pr_number,
            github_comment_id__isnull=False,
        )
        .order_by("-created_at")
        .values_list("github_comment_id", flat=True)
        .first()
    )

    result = github.create_or_update_issue_comment(
        repo_name,
        pr_number,
        body,
        comment_id=existing_comment_id,
    )

    if result.get("success"):
        comment_id = result["comment_id"]
        for _, plan in plans:
            plan.github_comment_id = comment_id
            plan.save(update_fields=["github_comment_id"])
    else:
        logger.warning(
            "post_plan_comment: failed to post comment",
            pr_number=pr_number,
            error=result.get("error"),
        )


def render_apply_comment(plan: GitHubSyncPlan) -> str:
    """Render an apply result comment for a single plan."""
    plan_data = plan.plan
    lines: list[str] = ["### PostHog data modeling plan — applied", ""]

    total = sum(len(v) for v in plan_data.get("models", {}).values()) + sum(
        len(v) for v in plan_data.get("dags", {}).values()
    )

    if total == 0:
        lines.append("No data modeling changes were applied.")
        return "\n".join(lines)

    change_word = "change" if total == 1 else "changes"
    lines.append(f"**{total} {change_word}** applied from this PR.")
    lines.append("")
    lines.extend(_render_plan_section(plan_data))
    lines.append(f"> Applied at commit `{plan.applied_sha[:7]}`.")
    return "\n".join(lines)


def render_combined_apply_comment(plans: list[tuple[str, GitHubSyncPlan]]) -> str:
    """Render apply results for multiple environments into a single comment."""
    lines: list[str] = ["### PostHog data modeling plan — applied", ""]

    total = 0
    for _, plan in plans:
        plan_data = plan.plan
        total += sum(len(v) for v in plan_data.get("models", {}).values())
        total += sum(len(v) for v in plan_data.get("dags", {}).values())

    if total == 0:
        lines.append("No data modeling changes were applied.")
        return "\n".join(lines)

    change_word = "change" if total == 1 else "changes"
    lines.append(f"**{total} {change_word}** applied from this PR.")
    lines.append("")

    for env_name, plan in plans:
        section = _render_plan_section(plan.plan)
        if section:
            lines.append(f"#### {env_name}")
            lines.append("")
            lines.extend(section)

    applied_sha = plans[0][1].applied_sha
    lines.append(f"> Applied at commit `{applied_sha[:7]}`.")
    return "\n".join(lines)


def _plan_has_changes(plan: GitHubSyncPlan) -> bool:
    plan_data = plan.plan
    total = sum(len(v) for v in plan_data.get("models", {}).values()) + sum(
        len(v) for v in plan_data.get("dags", {}).values()
    )
    return total > 0


def post_apply_comment(
    plans: list[GitHubSyncPlan],
    config: GitHubSyncConfig,
) -> None:
    """Post a new comment on the PR confirming the apply succeeded."""
    if not config.integration:
        return

    # only comment for plans that had actual changes
    plans = [p for p in plans if _plan_has_changes(p)]
    if not plans:
        return

    # group by PR number — there should typically be one, but be safe
    by_pr: dict[int, list[GitHubSyncPlan]] = {}
    for plan in plans:
        by_pr.setdefault(plan.pr_number, []).append(plan)

    github = GitHubIntegration(config.integration)
    repo_name = _extract_repo_name(config.repository)

    for pr_number, pr_plans in by_pr.items():
        if len(pr_plans) == 1:
            body = render_apply_comment(pr_plans[0])
        else:
            body = render_combined_apply_comment([(config.environment_name, p) for p in pr_plans])

        result = github.create_or_update_issue_comment(
            repo_name,
            pr_number,
            body,
        )

        if not result.get("success"):
            logger.warning(
                "post_apply_comment: failed to post comment",
                pr_number=pr_number,
                error=result.get("error"),
            )
