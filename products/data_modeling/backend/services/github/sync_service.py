"""Core sync service for GitHub-backed data modeling.

Handles syncing model files from a GitHub repo into PostHog's
DataWarehouseSavedQuery records and DAG.

The sync is one-directional in this module: GitHub -> PostHog.
GitHub is the source of truth once connected.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

import structlog

from products.data_modeling.backend.models import GitHubSyncConfig, GitHubSyncedModel, GitHubSyncStatus, Node
from products.data_modeling.backend.services.github.config_parser import DAG_TOML, parse_dag_config
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
    # Parse dag configs for sync frequency
    parsed_dag_configs: dict[str, timedelta | None] = {}
    for dag_path, dag_content in (dag_configs or {}).items():
        try:
            dag_config = parse_dag_config(dag_content)
            parsed_dag_configs[dag_path] = dag_config.sync_frequency_interval
        except ValueError as e:
            errors[dag_path] = str(e)
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
        # determine sync frequency from the nearest dag.toml
        sync_frequency_interval = _resolve_dag_sync_frequency(file.path, parsed_dag_configs)
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
            # sync to dag outside transaction (handles node creation)
            try:
                sync_saved_query_to_dag(saved_query, materialize=parsed.materialized)
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


def _resolve_dag_sync_frequency(file_path: str, dag_configs: dict[str, timedelta | None]) -> timedelta | None:
    """Find the sync frequency from the nearest dag.toml to a model file.

    For a file at models/core/revenue.sql, looks for dag configs at:
    - models/core/dag.toml
    - models/dag.toml

    Returns the first match, or None if no dag.toml is found.
    """
    parts = file_path.split("/")
    # walk up from the file's directory to find the nearest dag.toml
    for i in range(len(parts) - 1, 0, -1):
        dag_path = "/".join(parts[:i]) + "/" + DAG_TOML
        if dag_path in dag_configs:
            return dag_configs[dag_path]
    return None
