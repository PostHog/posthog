from posthog.test.base import BaseTest

from products.data_warehouse.backend.models.external_data_job import ExternalDataJob
from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.types import ExternalDataSourceType


class TestExternalDataSchemaFolderPath(BaseTest):
    def setUp(self):
        super().setUp()
        self.source = ExternalDataSource.objects.create(
            source_id="source-id",
            connection_id="connection-id",
            destination_id="destination-id",
            team=self.team,
            sync_frequency=ExternalDataSource.SyncFrequency.DAILY,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.MYSQL,
            prefix="prefix",
        )
        self.schema = ExternalDataSchema.objects.create(
            name="messages",
            team=self.team,
            source=self.source,
        )

    def test_folder_path_uses_explicit_source_type_without_db_lookup(self):
        # Re-fetch the schema *without* prefetching `source` to mimic the
        # state after `refresh_from_db()` has cleared the FK cache.
        schema = ExternalDataSchema.objects.get(id=self.schema.id)
        assert "source" not in schema._state.fields_cache

        # Passing `source_type` explicitly must avoid touching `self.source`
        # entirely — under pgbouncer pressure that lookup turns into a fresh
        # connection attempt during exception unwinding (signal cb9c9ad6).
        with self.assertNumQueries(0):
            path = schema.folder_path(source_type="custom_type")

        assert path == f"team_{self.team.id}_custom_type_{schema.id}".lower().replace("-", "_")

    def test_folder_path_falls_back_to_self_source_when_source_type_missing(self):
        # Default behavior is preserved for callers (admin, tests) that don't
        # pass `source_type` and accept the lazy FK dereference.
        path = self.schema.folder_path()
        assert ExternalDataSourceType.MYSQL.value.lower() in path

    def test_folder_path_lowercases_and_replaces_dashes(self):
        path = self.schema.folder_path(source_type="SOME-Type")
        assert path == f"team_{self.team.id}_some_type_{self.schema.id}".lower().replace("-", "_")
        assert "-" not in path
        assert path == path.lower()


class TestExternalDataJobFolderPath(BaseTest):
    def setUp(self):
        super().setUp()
        self.source = ExternalDataSource.objects.create(
            source_id="source-id",
            connection_id="connection-id",
            destination_id="destination-id",
            team=self.team,
            sync_frequency=ExternalDataSource.SyncFrequency.DAILY,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.MYSQL,
            prefix="prefix",
        )
        self.schema = ExternalDataSchema.objects.create(
            name="messages",
            team=self.team,
            source=self.source,
        )
        self.job = ExternalDataJob.objects.create(
            team=self.team,
            pipeline=self.source,
            schema=self.schema,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
        )

    def test_folder_path_does_not_lazy_load_schema_source_when_pipeline_cached(self):
        # Reload the job with `pipeline` prefetched and the schema present,
        # but the schema's `source` cache cleared — exactly the state after
        # `finalize_desc_sort_incremental_value` calls `refresh_from_db()`
        # on the schema during a sync that's about to fail.
        job = ExternalDataJob.objects.select_related("pipeline", "schema").get(id=self.job.id)
        assert job.schema is not None
        assert "source" not in job.schema._state.fields_cache

        # Path should be derived purely from in-memory state — no extra
        # queries beyond the ones `select_related` already satisfied.
        with self.assertNumQueries(0):
            path = job.folder_path()

        expected_source_type = ExternalDataSourceType.MYSQL.value.lower()
        assert expected_source_type in path
        assert str(self.team.id) in path
        # The schema's source FK cache must remain untouched — the whole
        # point of the fix is to avoid populating it on this path.
        assert "source" not in job.schema._state.fields_cache

    def test_folder_path_falls_back_to_schema_source_cache_when_pipeline_missing(self):
        # Defensive path: pipeline FK cache absent, schema.source cache present.
        # We should still avoid a fresh DB query.
        job = ExternalDataJob.objects.get(id=self.job.id)
        assert "pipeline" not in job._state.fields_cache
        # Force-load the schema's source so it's cached on the schema instance.
        schema = job.schema
        assert schema is not None
        _ = schema.source  # populate fields_cache["source"]

        # `self.schema` access counts as a query if not cached — we already
        # did it above, so the cache is warm. No further queries expected.
        with self.assertNumQueries(0):
            path = job.folder_path()

        assert ExternalDataSourceType.MYSQL.value.lower() in path

    def test_folder_path_raises_when_schema_missing(self):
        job = ExternalDataJob.objects.create(
            team=self.team,
            pipeline=self.source,
            schema=None,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
        )

        with self.assertRaises(ValueError):
            job.folder_path()
