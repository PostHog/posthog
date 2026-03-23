from datetime import timedelta

import pytest
from posthog.test.base import BaseTest

from products.data_modeling.backend.models import GitHubSyncConfig, GitHubSyncedModel, GitHubSyncStatus
from products.data_modeling.backend.services.gitsync.sync_service import SyncedFile, sync_models_from_files
from products.data_warehouse.backend.models import DataWarehouseSavedQuery


def _make_file(path: str, content: str, sha: str | None = None) -> SyncedFile:
    return SyncedFile(path=path, content=content, sha=sha or f"sha_{path}")


@pytest.mark.django_db
class TestSyncModelsFromFiles(BaseTest):
    def setUp(self):
        super().setUp()
        self.config, _ = GitHubSyncConfig.objects.update_or_create(
            team=self.team,
            defaults={
                "repository": "org/repo",
                "environment_name": "production",
            },
        )

    def test_creates_new_model(self):
        files = [_make_file("models/revenue.sql", "SELECT 1")]
        result = sync_models_from_files(team=self.team, config=self.config, files=files, commit_sha="abc123")

        assert result.created == ["models/revenue.sql"]
        assert result.updated == []
        assert result.deleted == []

        sq = DataWarehouseSavedQuery.objects.get(team=self.team, name="revenue")
        assert sq.query == {"query": "SELECT 1", "kind": "HogQLQuery"}

        synced = GitHubSyncedModel.objects.get(team=self.team, file_path="models/revenue.sql")
        assert synced.saved_query == sq
        assert synced.file_sha == "sha_models/revenue.sql"
        assert synced.last_synced_sha == "abc123"

    def test_updates_existing_model(self):
        files_v1 = [_make_file("models/revenue.sql", "SELECT 1", sha="sha_v1")]
        sync_models_from_files(team=self.team, config=self.config, files=files_v1, commit_sha="commit1")

        files_v2 = [_make_file("models/revenue.sql", "SELECT 2", sha="sha_v2")]
        result = sync_models_from_files(team=self.team, config=self.config, files=files_v2, commit_sha="commit2")

        assert result.created == []
        assert result.updated == ["models/revenue.sql"]

        sq = DataWarehouseSavedQuery.objects.get(team=self.team, name="revenue")
        assert sq.query["query"] == "SELECT 2"

    def test_skips_unchanged_files(self):
        files = [_make_file("models/revenue.sql", "SELECT 1", sha="same_sha")]
        sync_models_from_files(team=self.team, config=self.config, files=files, commit_sha="commit1")

        result = sync_models_from_files(team=self.team, config=self.config, files=files, commit_sha="commit2")

        assert result.created == []
        assert result.updated == []
        assert result.deleted == []

    def test_deletes_removed_model(self):
        files = [
            _make_file("models/a.sql", "SELECT 1"),
            _make_file("models/b.sql", "SELECT 2"),
        ]
        sync_models_from_files(team=self.team, config=self.config, files=files, commit_sha="commit1")

        assert DataWarehouseSavedQuery.objects.filter(team=self.team, deleted=False).count() == 2

        # Second sync only has file a
        files_v2 = [_make_file("models/a.sql", "SELECT 1")]
        result = sync_models_from_files(team=self.team, config=self.config, files=files_v2, commit_sha="commit2")

        assert result.deleted == ["models/b.sql"]
        assert GitHubSyncedModel.objects.filter(team=self.team).count() == 1

        deleted_sq = DataWarehouseSavedQuery.objects.get(team=self.team, deleted_name="b")
        assert deleted_sq.deleted is True

    def test_multiple_files_created(self):
        files = [
            _make_file("models/a.sql", "SELECT 1"),
            _make_file("models/b.sql", "SELECT 2"),
            _make_file("models/c.sql", "SELECT 3"),
        ]
        result = sync_models_from_files(team=self.team, config=self.config, files=files, commit_sha="abc")

        assert len(result.created) == 3
        assert DataWarehouseSavedQuery.objects.filter(team=self.team, deleted=False).count() == 3

    def test_invalid_file_records_error(self):
        files = [
            _make_file("models/good.sql", "SELECT 1"),
            _make_file("models/bad.sql", "-- @materialize true\nSELECT 1"),  # nullary with value
        ]
        result = sync_models_from_files(team=self.team, config=self.config, files=files, commit_sha="abc")

        assert result.created == ["models/good.sql"]
        assert "models/bad.sql" in result.errors

    def test_empty_file_records_error(self):
        files = [_make_file("models/empty.sql", "-- @materialize")]
        result = sync_models_from_files(team=self.team, config=self.config, files=files, commit_sha="abc")

        assert "models/empty.sql" in result.errors

    def test_updates_config_state_on_success(self):
        files = [_make_file("models/a.sql", "SELECT 1")]
        sync_models_from_files(team=self.team, config=self.config, files=files, commit_sha="abc123")

        self.config.refresh_from_db()
        assert self.config.last_synced_sha == "abc123"
        assert self.config.last_synced_at is not None
        assert self.config.sync_status == GitHubSyncStatus.IDLE
        assert self.config.last_sync_error == ""

    def test_updates_config_state_on_errors(self):
        files = [_make_file("models/bad.sql", "-- @materialize")]
        sync_models_from_files(team=self.team, config=self.config, files=files, commit_sha="abc")

        self.config.refresh_from_db()
        assert self.config.sync_status == GitHubSyncStatus.ERROR
        assert self.config.last_sync_error != ""

    def test_skips_when_already_syncing(self):
        self.config.sync_status = GitHubSyncStatus.SYNCING
        self.config.save(update_fields=["sync_status"])

        files = [_make_file("models/a.sql", "SELECT 1")]
        result = sync_models_from_files(team=self.team, config=self.config, files=files, commit_sha="abc")

        assert "_sync" in result.errors
        assert DataWarehouseSavedQuery.objects.filter(team=self.team).count() == 0

    def test_materialized_annotation(self):
        files = [_make_file("models/matview.sql", "-- @materialize\nSELECT 1")]
        sync_models_from_files(team=self.team, config=self.config, files=files, commit_sha="abc")

        sq = DataWarehouseSavedQuery.objects.get(team=self.team, name="matview")
        assert sq.query["query"] == "SELECT 1"

    def test_description_annotation(self):
        files = [_make_file("models/described.sql", "-- @description My model\nSELECT 1")]
        sync_models_from_files(team=self.team, config=self.config, files=files, commit_sha="abc")

        sq = DataWarehouseSavedQuery.objects.get(team=self.team, name="described")
        assert sq.query["query"] == "SELECT 1"

    def test_model_name_from_nested_path(self):
        files = [_make_file("models/staging/stg_events.sql", "SELECT 1")]
        sync_models_from_files(team=self.team, config=self.config, files=files, commit_sha="abc")

        assert DataWarehouseSavedQuery.objects.filter(team=self.team, name="stg_events").exists()

    def test_dag_config_sets_sync_frequency(self):
        files = [_make_file("models/core/matview.sql", "-- @materialize\nSELECT 1")]
        dag_configs = {"models/core/dag.toml": 'sync_frequency = "1h"'}
        sync_models_from_files(
            team=self.team, config=self.config, files=files, commit_sha="abc", dag_configs=dag_configs
        )

        sq = DataWarehouseSavedQuery.objects.get(team=self.team, name="matview")
        assert sq.sync_frequency_interval == timedelta(hours=1)

    def test_dag_config_no_sync_frequency_for_views(self):
        files = [_make_file("models/core/view.sql", "SELECT 1")]
        dag_configs = {"models/core/dag.toml": 'sync_frequency = "1h"'}
        sync_models_from_files(
            team=self.team, config=self.config, files=files, commit_sha="abc", dag_configs=dag_configs
        )

        sq = DataWarehouseSavedQuery.objects.get(team=self.team, name="view")
        assert sq.sync_frequency_interval is None

    def test_dag_config_walks_up_directories(self):
        files = [_make_file("models/core/deep/matview.sql", "-- @materialize\nSELECT 1")]
        dag_configs = {"models/core/dag.toml": 'sync_frequency = "6h"'}
        sync_models_from_files(
            team=self.team, config=self.config, files=files, commit_sha="abc", dag_configs=dag_configs
        )

        sq = DataWarehouseSavedQuery.objects.get(team=self.team, name="matview")
        assert sq.sync_frequency_interval == timedelta(hours=6)

    def test_invalid_dag_config_records_error(self):
        files = [_make_file("models/a.sql", "SELECT 1")]
        dag_configs = {"models/dag.toml": 'sync_frequency = "invalid"'}
        result = sync_models_from_files(
            team=self.team, config=self.config, files=files, commit_sha="abc", dag_configs=dag_configs
        )

        assert "models/dag.toml" in result.errors

    def test_total_changes(self):
        files = [_make_file("models/a.sql", "SELECT 1"), _make_file("models/b.sql", "SELECT 2")]
        result = sync_models_from_files(team=self.team, config=self.config, files=files, commit_sha="abc")

        assert result.total_changes == 2
