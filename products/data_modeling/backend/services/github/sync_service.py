"""Core sync service for GitHub-backed data modeling.

Handles syncing model files from a GitHub repo into PostHog's
DataWarehouseSavedQuery records and DAG.

The sync is one-directional in this module: GitHub -> PostHog.
GitHub is the source of truth once connected.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.models.integration import GitHubIntegration

from products.data_modeling.backend.models import GitHubSyncConfig, GitHubSyncedModel, GitHubSyncStatus, Node
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.services.github.config_parser import DAG_TOML, DAGConfig, parse_dag_config
from products.data_modeling.backend.services.github.model_parser import model_name_from_path, parse_model_file
from products.data_modeling.backend.services.saved_query_dag_sync import sync_saved_query_to_dag
from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

if TYPE_CHECKING:
    from posthog.models import Team

logger = structlog.get_logger(__name__)


@dataclass
class SyncedFile:
    """A file from the GitHub repo to sync."""

    path: str
    content: str
    sha: str  # git blob sha


@dataclass
class SyncResult:
    """Result of a sync operation."""

    created: list[str]
    updated: list[str]
    deleted: list[str]
    errors: dict[str, str]  # path -> error message

    @property
    def total_changes(self) -> int:
        return len(self.created) + len(self.updated) + len(self.deleted)


def sync_models_from_files(
    *,
    team: "Team",
    config: GitHubSyncConfig,
    files: list[SyncedFile],
    commit_sha: str,
    dag_configs: dict[str, str] | None = None,
) -> SyncResult:
    """Sync a set of model files from GitHub into PostHog.

    This is the core sync function. It:
    1. Parses each .sql file
    2. Creates/updates DataWarehouseSavedQuery records
    3. Removes models that no longer exist in the repo
    4. Syncs each changed model to the DAG
    5. Updates the GitHubSyncConfig with the new commit SHA

    Args:
        team: The PostHog team to sync into
        config: The GitHubSyncConfig for this team
        files: List of .sql files from the repo (full contents)
        commit_sha: The commit SHA being synced
        dag_configs: Optional dict of dag directory path -> dag.toml content
    """
    # Acquire a lock on the config row and check it's not already syncing.
    # This prevents concurrent syncs from webhooks and polling overlapping.
    with transaction.atomic():
        locked_config = GitHubSyncConfig.objects.select_for_update().get(pk=config.pk)
        if locked_config.sync_status == GitHubSyncStatus.SYNCING:
            logger.info("Sync already in progress, skipping", team_id=team.id, commit_sha=commit_sha)
            return SyncResult(created=[], updated=[], deleted=[], errors={"_sync": "Sync already in progress"})
        locked_config.sync_status = GitHubSyncStatus.SYNCING
        locked_config.save(update_fields=["sync_status"])

    created: list[str] = []
    updated: list[str] = []
    deleted: list[str] = []
    errors: dict[str, str] = {}
    # Parse dag configs into DAGConfig objects (used for both sync frequency and DAG assignment)
    parsed_dag_configs: dict[str, DAGConfig] = {}
    for dag_path, dag_content in (dag_configs or {}).items():
        try:
            parsed_dag_configs[dag_path] = parse_dag_config(dag_content)
        except ValueError as e:
            errors[dag_path] = str(e)
    # Pre-create DAG objects for each dag.toml directory
    dag_objects: dict[str, DAG] = {}
    for dag_path, dag_cfg in parsed_dag_configs.items():
        dag_name = dag_cfg.name or _dag_name_from_toml_path(dag_path)
        dag_dir = dag_path.rsplit("/", 1)[0] if "/" in dag_path else ""
        dag_obj, _ = DAG.objects.update_or_create(
            team=team,
            name=dag_name,
            defaults={
                "description": dag_cfg.description,
                "sync_frequency_interval": dag_cfg.sync_frequency_interval,
                "source_control_path": dag_dir,
            },
        )
        dag_objects[dag_path] = dag_obj
    default_dag = DAG.get_or_create_default(team)
    # track which file paths we see in this sync
    seen_paths: set[str] = set()
    for file in files:
        seen_paths.add(file.path)
        existing_synced = GitHubSyncedModel.objects.filter(team=team, file_path=file.path).first()
        if existing_synced and existing_synced.file_sha == file.sha:
            continue  # unchanged
        try:
            parsed = parse_model_file(file.content)
        except ValueError as e:
            errors[file.path] = str(e)
            logger.warning("Failed to parse model file", path=file.path, error=str(e), team_id=team.id)
            continue
        model_name = model_name_from_path(file.path)
        # resolve the nearest dag.toml for sync frequency and DAG assignment
        nearest_dag_path = _resolve_nearest_dag_toml(file.path, parsed_dag_configs)
        sync_frequency_interval = (
            parsed_dag_configs[nearest_dag_path].sync_frequency_interval if nearest_dag_path else None
        )
        dag = dag_objects[nearest_dag_path] if nearest_dag_path else default_dag
        try:
            with transaction.atomic():
                saved_query, query_created = DataWarehouseSavedQuery.objects.update_or_create(
                    team=team,
                    name=model_name,
                    defaults={
                        "query": {"query": parsed.query, "kind": "HogQLQuery"},
                        "sync_frequency_interval": sync_frequency_interval if parsed.materialized else None,
                    },
                )
                GitHubSyncedModel.objects.update_or_create(
                    team=team,
                    file_path=file.path,
                    defaults={
                        "saved_query": saved_query,
                        "file_sha": file.sha,
                        "last_synced_sha": commit_sha,
                    },
                )
            if query_created:
                created.append(file.path)
            else:
                updated.append(file.path)
            # if the model moved to a different DAG, remove the old node first
            Node.objects.filter(saved_query=saved_query, team=team).exclude(dag=dag).delete()
            # sync to dag outside transaction (handles node creation)
            try:
                node = sync_saved_query_to_dag(saved_query, materialize=parsed.materialized, dag=dag)
                if node is not None:
                    Node.objects.filter(pk=node.pk).update(source_control_path=file.path)
            except Exception as e:
                logger.warning("Failed to sync model to DAG", path=file.path, error=str(e), team_id=team.id)
                errors[file.path] = f"DAG sync failed: {e}"
        except Exception as e:
            errors[file.path] = str(e)
            logger.exception("Failed to sync model", path=file.path, team_id=team.id)
    # delete models that are no longer in the repo
    orphaned = (
        GitHubSyncedModel.objects.filter(team=team).exclude(file_path__in=seen_paths).select_related("saved_query")
    )
    for orphan in orphaned:
        try:
            file_path = orphan.file_path
            Node.objects.filter(saved_query=orphan.saved_query).delete()
            orphan.saved_query.soft_delete()
            orphan.delete()
            deleted.append(file_path)
        except Exception as e:
            errors[orphan.file_path] = f"Failed to delete: {e}"
            logger.exception("Failed to delete orphaned model", path=orphan.file_path, team_id=team.id)
    # clean up stale DAG assignments (e.g. model moved between directories)
    # and empty DAGs (e.g. dag.toml directory removed from repo)
    active_dag_ids = {d.id for d in dag_objects.values()} | {default_dag.id}
    _cleanup_stale_dags(team, active_dag_ids)
    # update state
    config.last_synced_sha = commit_sha
    config.last_synced_at = timezone.now()
    config.sync_status = GitHubSyncStatus.ERROR if errors else GitHubSyncStatus.IDLE
    config.last_sync_error = "; ".join(f"{path}: {err}" for path, err in errors.items()) if errors else ""
    config.save(update_fields=["last_synced_sha", "last_synced_at", "sync_status", "last_sync_error"])
    logger.info(
        "Sync completed",
        team_id=team.id,
        commit_sha=commit_sha,
        created=len(created),
        updated=len(updated),
        deleted=len(deleted),
        errors=len(errors),
    )
    return SyncResult(created=created, updated=updated, deleted=deleted, errors=errors)


def sync_from_github(*, team: "Team", config: GitHubSyncConfig) -> SyncResult:
    """Fetch all model files from the GitHub repo and sync them into PostHog.

    This is the main entry point for both webhook-triggered and manual syncs.
    It:
    1. Gets the repo tree from GitHub
    2. Filters for .sql files in the models directory
    3. Fetches the content of each file
    4. Passes everything to sync_models_from_files
    """
    if not config.integration:
        return SyncResult(created=[], updated=[], deleted=[], errors={"_config": "No GitHub integration configured"})
    if not config.repository:
        return SyncResult(created=[], updated=[], deleted=[], errors={"_config": "No repository configured"})
    github = GitHubIntegration(config.integration)
    if github.access_token_expired():
        github.refresh_access_token()
    repo_name = _extract_repo_name(config.repository)
    default_branch = github.get_default_branch(repo_name)
    models_dir = config.models_directory or "models"
    env_name = config.environment_name
    # Get the tree to find all files
    tree_result = github.get_tree(repo_name, tree_sha=default_branch)
    if not tree_result.get("success"):
        error = tree_result.get("error", "Unknown error fetching tree")
        logger.error("Failed to fetch repo tree", team_id=team.id, error=error)
        return SyncResult(created=[], updated=[], deleted=[], errors={"_tree": error})
    tree_items = tree_result["tree"]
    is_multi_env = GitHubSyncConfig.objects.filter(repository=config.repository).count() > 1
    if is_multi_env:
        base_prefix = f"{models_dir}/{env_name}/"
    else:
        base_prefix = f"{models_dir}/"
    # Filter for .sql and dag.toml files under the models directory
    sql_items = []
    dag_toml_items = []
    for item in tree_items:
        if not item["path"].startswith(base_prefix):
            continue
        if item["path"].endswith(".sql"):
            sql_items.append(item)
        elif item["path"].endswith(DAG_TOML):
            dag_toml_items.append(item)
    # Fetch content for all relevant files
    commit_sha = tree_result["sha"]
    files: list[SyncedFile] = []
    dag_configs: dict[str, str] = {}
    for item in sql_items:
        content_result = github.get_file_content(repo_name, item["path"], ref=default_branch)
        if content_result.get("success"):
            files.append(
                SyncedFile(
                    path=item["path"],
                    content=content_result["content"],
                    sha=item["sha"],
                )
            )
        else:
            logger.warning(
                "Failed to fetch file content",
                path=item["path"],
                error=content_result.get("error"),
                team_id=team.id,
            )
    for item in dag_toml_items:
        content_result = github.get_file_content(repo_name, item["path"], ref=default_branch)
        if content_result.get("success"):
            dag_configs[item["path"]] = content_result["content"]
    return sync_models_from_files(
        team=team,
        config=config,
        files=files,
        commit_sha=commit_sha,
        dag_configs=dag_configs,
    )


def _extract_repo_name(repository: str) -> str:
    """Extract just the repo name from 'org/repo' format.

    GitHubIntegration methods expect just the repo name (not full_name),
    since they prepend the org from the integration config.
    """
    if "/" in repository:
        return repository.split("/", 1)[1]
    return repository


def _resolve_nearest_dag_toml(file_path: str, dag_configs: dict[str, DAGConfig]) -> str | None:
    """Find the nearest dag.toml path for a model file.

    For a file at models/core/revenue.sql, looks for dag configs at:
    - models/core/dag.toml
    - models/dag.toml

    Returns the dag.toml path, or None if no dag.toml is found.
    """
    parts = file_path.split("/")
    for i in range(len(parts) - 1, 0, -1):
        dag_path = "/".join(parts[:i]) + "/" + DAG_TOML
        if dag_path in dag_configs:
            return dag_path
    return None


def _dag_name_from_toml_path(dag_toml_path: str) -> str:
    """Derive a DAG name from a dag.toml file path.

    The DAG name is the parent directory name of the dag.toml file.
    For example:
    - models/production/finance/dag.toml -> "finance"
    - models/marketing/dag.toml -> "marketing"
    """
    parts = dag_toml_path.rstrip("/").split("/")
    # parent directory of dag.toml
    if len(parts) >= 2:
        return parts[-2]
    return parts[0]


def _cleanup_stale_dags(team: "Team", active_dag_ids: set) -> None:
    """Remove nodes from DAGs that are no longer active and delete empty DAGs.

    Handles two cases:
    1. A model moved between directories — its old node on the previous DAG
       is now stale (sync_saved_query_to_dag created a new node on the new DAG).
    2. A dag.toml directory was removed — the entire DAG is now empty.

    Conflict DAGs (used for cycle detection DLQ) are never touched.
    """
    stale_dags = DAG.objects.filter(team=team).exclude(id__in=active_dag_ids).exclude(name__startswith="conflict_")

    for dag in stale_dags:
        stale_node_count = Node.objects.filter(team=team, dag=dag).count()
        if stale_node_count > 0:
            logger.info(
                "Cleaning up stale DAG nodes",
                team_id=team.id,
                dag_name=dag.name,
                node_count=stale_node_count,
            )
            Node.objects.filter(team=team, dag=dag).delete()
        dag.delete()
        logger.info("Deleted stale DAG", team_id=team.id, dag_name=dag.name)
