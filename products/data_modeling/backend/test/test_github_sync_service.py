from datetime import timedelta

import pytest
from posthog.test.base import BaseTest

from products.data_modeling.backend.models import GitHubSyncConfig, GitHubSyncedModel, GitHubSyncStatus
from products.data_modeling.backend.services.github.sync_service import (
    SyncedFile,
    _extract_table_refs_from_query,
    _topological_sort_files,
    sync_models_from_files,
)
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
        assert sq.query["query"] == "-- @materialize\nSELECT 1"

    def test_description_annotation(self):
        files = [_make_file("models/described.sql", "-- @description My model\nSELECT 1")]
        sync_models_from_files(team=self.team, config=self.config, files=files, commit_sha="abc")

        sq = DataWarehouseSavedQuery.objects.get(team=self.team, name="described")
        assert sq.query["query"] == "-- @description My model\nSELECT 1"

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

    def test_creates_dependent_models_in_topological_order(self):
        # c depends on b, b depends on a — pass them in reverse order
        files = [
            _make_file("models/c.sql", "SELECT * FROM b"),
            _make_file("models/b.sql", "SELECT * FROM a"),
            _make_file("models/a.sql", "SELECT 1"),
        ]
        result = sync_models_from_files(team=self.team, config=self.config, files=files, commit_sha="abc")

        assert len(result.created) == 3
        # a should be created before b, and b before c
        assert result.created.index("models/a.sql") < result.created.index("models/b.sql")
        assert result.created.index("models/b.sql") < result.created.index("models/c.sql")


class TestExtractTableRefsFromQuery:
    def test_simple_from(self):
        assert _extract_table_refs_from_query("SELECT * FROM events") == {"events"}

    def test_join(self):
        refs = _extract_table_refs_from_query("SELECT * FROM events JOIN persons ON events.person_id = persons.id")
        assert refs == {"events", "persons"}

    def test_cte_resolves_through(self):
        query = "WITH cte AS (SELECT * FROM events) SELECT * FROM cte"
        assert _extract_table_refs_from_query(query) == {"events"}

    def test_subquery_not_treated_as_table(self):
        query = "SELECT * FROM (SELECT * FROM events)"
        assert _extract_table_refs_from_query(query) == {"events"}

    def test_union(self):
        query = "SELECT * FROM events UNION ALL SELECT * FROM persons"
        assert _extract_table_refs_from_query(query) == {"events", "persons"}

    def test_invalid_sql_returns_empty(self):
        assert _extract_table_refs_from_query("NOT VALID SQL ???") == set()

    def test_annotations_ignored(self):
        query = "-- @materialize\nSELECT * FROM events"
        assert _extract_table_refs_from_query(query) == {"events"}


class TestTopologicalSortFiles:
    def test_single_file_unchanged(self):
        files = [_make_file("models/a.sql", "SELECT 1")]
        assert _topological_sort_files(files) == files

    def test_independent_files_all_returned(self):
        files = [
            _make_file("models/a.sql", "SELECT 1"),
            _make_file("models/b.sql", "SELECT 2"),
        ]
        result = _topological_sort_files(files)
        assert len(result) == 2

    def test_dependency_ordered_before_dependent(self):
        files = [
            _make_file("models/child.sql", "SELECT * FROM parent"),
            _make_file("models/parent.sql", "SELECT 1"),
        ]
        result = _topological_sort_files(files)
        names = [f.path for f in result]
        assert names.index("models/parent.sql") < names.index("models/child.sql")

    def test_chain_dependency(self):
        files = [
            _make_file("models/c.sql", "SELECT * FROM b"),
            _make_file("models/a.sql", "SELECT 1"),
            _make_file("models/b.sql", "SELECT * FROM a"),
        ]
        result = _topological_sort_files(files)
        names = [f.path for f in result]
        assert names.index("models/a.sql") < names.index("models/b.sql")
        assert names.index("models/b.sql") < names.index("models/c.sql")

    def test_diamond_dependency(self):
        files = [
            _make_file("models/d.sql", "SELECT * FROM b JOIN c ON 1=1"),
            _make_file("models/c.sql", "SELECT * FROM a"),
            _make_file("models/b.sql", "SELECT * FROM a"),
            _make_file("models/a.sql", "SELECT 1"),
        ]
        result = _topological_sort_files(files)
        names = [f.path for f in result]
        assert names.index("models/a.sql") < names.index("models/b.sql")
        assert names.index("models/a.sql") < names.index("models/c.sql")
        assert names.index("models/b.sql") < names.index("models/d.sql")
        assert names.index("models/c.sql") < names.index("models/d.sql")

    def test_external_dependency_ignored(self):
        files = [
            _make_file("models/child.sql", "SELECT * FROM external_table"),
            _make_file("models/parent.sql", "SELECT 1"),
        ]
        result = _topological_sort_files(files)
        # both files returned, no crash from unknown reference
        assert len(result) == 2

    def test_cycle_does_not_crash(self):
        files = [
            _make_file("models/a.sql", "SELECT * FROM b"),
            _make_file("models/b.sql", "SELECT * FROM a"),
        ]
        result = _topological_sort_files(files)
        # all files still returned even with a cycle
        assert len(result) == 2

    def test_unparseable_sql_does_not_block_sort(self):
        files = [
            _make_file("models/bad.sql", "NOT VALID SQL ???"),
            _make_file("models/good.sql", "SELECT 1"),
        ]
        result = _topological_sort_files(files)
        assert len(result) == 2
