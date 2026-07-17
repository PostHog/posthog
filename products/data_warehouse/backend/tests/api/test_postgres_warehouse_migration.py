"""Integration tests for Postgres warehouse-mode migration of legacy unqualified rows.

Covers `consolidate_postgres_legacy_rows` (called from `refresh_schemas`) and
`apply_on_schema_clear` (called from PATCH when `job_inputs.schema` is dropped). Both code paths
sit in `products/data_warehouse/backend/postgres_warehouse_migration.py`; these tests exercise
them end-to-end through the DRF viewset to confirm the migration is observable from the API.
"""

import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

from rest_framework import status

from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema


class TestPostgresWarehouseMigration(APIBaseTest):
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_qualifies_legacy_warehouse_rows_in_place(self, mock_get_source):
        # A pre-PR warehouse Postgres source had `schema=public` on the source config and
        # `ExternalDataSchema.name="auth_group"` (no schema prefix). After this PR, discovery
        # returns the qualified `public.auth_group`. `consolidate_postgres_legacy_rows` qualifies
        # the legacy row in place and stores `s3_folder_name="auth_group"` so the next sync
        # writes to the original Delta path — no orphaned data, but the row picks up the new
        # qualified naming so tables from other schemas can coexist without a name collision.
        mock_get_source.return_value.parse_config.return_value = None
        mock_get_source.return_value.get_version_deprecation.return_value = None
        mock_get_source.return_value.get_schemas.return_value = [
            SourceSchema(
                name="public.auth_group",
                supports_incremental=False,
                supports_append=False,
                columns=[("id", "integer", False)],
                foreign_keys=[],
                source_schema="public",
                source_table_name="auth_group",
            ),
        ]
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="legacy",
            access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
            job_inputs={"host": "localhost", "port": 5432, "schema": "public"},
        )
        legacy_table = DataWarehouseTable.objects.create(
            name="legacypostgres_auth_group",
            format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            team=self.team,
            url_pattern="https://bucket/team_X_postgres_auth_group/*",
            external_data_source=source,
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64"}},
        )
        legacy_schema = ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source_id=source.pk,
            name="auth_group",
            should_sync=True,
            table=legacy_table,
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )
        assert response.status_code == status.HTTP_200_OK

        legacy_schema.refresh_from_db()
        legacy_table.refresh_from_db()
        # Row gets the qualified name so multi-schema discovery doesn't collide later.
        assert legacy_schema.name == "public.auth_group"
        # s3_folder_name locks the Delta path to the legacy folder so existing data is preserved.
        assert legacy_schema.s3_folder_name == "auth_group"
        # schema_metadata pinned so source_for_pipeline knows the canonical (schema, table) tuple.
        metadata = legacy_schema.sync_type_config.get("schema_metadata") or {}
        assert metadata.get("source_schema") == "public"
        assert metadata.get("source_table_name") == "auth_group"
        # DataWarehouseTable link + url_pattern untouched — no data orphaning.
        assert legacy_schema.table_id == legacy_table.id
        assert legacy_table.name == "legacypostgres_auth_group"
        assert legacy_table.url_pattern == "https://bucket/team_X_postgres_auth_group/*"
        # Discovery returned `public.auth_group` and we consolidated the legacy row into it —
        # no duplicate qualified row, no soft-deleted unqualified row.
        live_schemas = ExternalDataSchema.objects.filter(
            team_id=self.team.pk, source_id=source.pk, deleted=False
        ).values_list("name", flat=True)
        assert list(live_schemas) == ["public.auth_group"]

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_idempotent_on_legacy_warehouse_rows(self, mock_get_source):
        # Calling refresh_schemas twice on a legacy row should be a no-op on the second call —
        # name stays put, schema_metadata stays put, no thrash of updated_at.
        mock_get_source.return_value.parse_config.return_value = None
        mock_get_source.return_value.get_version_deprecation.return_value = None
        mock_get_source.return_value.get_schemas.return_value = [
            SourceSchema(
                name="public.auth_group",
                supports_incremental=False,
                supports_append=False,
                columns=[("id", "integer", False)],
                foreign_keys=[],
                source_schema="public",
                source_table_name="auth_group",
            ),
        ]
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="legacy",
            access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
            job_inputs={"host": "localhost", "port": 5432, "schema": "public"},
        )
        ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source_id=source.pk,
            name="auth_group",
            should_sync=True,
        )

        for _ in range(2):
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
            )
            assert response.status_code == status.HTTP_200_OK

        names = list(
            ExternalDataSchema.objects.filter(team_id=self.team.pk, source_id=source.pk, deleted=False).values_list(
                "name", flat=True
            )
        )
        # First refresh qualifies the legacy row in place; second refresh is a no-op (name already
        # qualified, no duplicate to consolidate).
        assert names == ["public.auth_group"]
        schema = ExternalDataSchema.objects.get(team_id=self.team.pk, source_id=source.pk, name="public.auth_group")
        metadata = schema.sync_type_config.get("schema_metadata") or {}
        assert metadata.get("source_schema") == "public"
        assert metadata.get("source_table_name") == "auth_group"
        assert schema.s3_folder_name == "auth_group"

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_refreshes_legacy_warehouse_metadata_when_columns_change(self, mock_get_source):
        # available_columns must keep up with upstream changes for legacy unqualified rows.
        # Without resolving the row by source location, reconcile_postgres_schemas would only
        # write metadata on the very first refresh and then leave the column-picker UI stale.
        mock_get_source.return_value.parse_config.return_value = None
        mock_get_source.return_value.get_version_deprecation.return_value = None
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="legacy",
            access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
            job_inputs={"host": "localhost", "port": 5432, "schema": "public"},
        )
        ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source_id=source.pk,
            name="auth_group",
            should_sync=True,
        )

        mock_get_source.return_value.get_schemas.return_value = [
            SourceSchema(
                name="public.auth_group",
                supports_incremental=False,
                supports_append=False,
                columns=[("id", "integer", False)],
                foreign_keys=[],
                source_schema="public",
                source_table_name="auth_group",
            ),
        ]
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )
        assert response.status_code == status.HTTP_200_OK

        mock_get_source.return_value.get_schemas.return_value = [
            SourceSchema(
                name="public.auth_group",
                supports_incremental=False,
                supports_append=False,
                columns=[("id", "integer", False), ("new_column", "text", True)],
                foreign_keys=[],
                source_schema="public",
                source_table_name="auth_group",
            ),
        ]
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )
        assert response.status_code == status.HTTP_200_OK

        # First refresh qualifies the row in place; second refresh's metadata write should still
        # land on the same row.
        schema = ExternalDataSchema.objects.get(team_id=self.team.pk, source_id=source.pk, name="public.auth_group")
        metadata_columns = (schema.sync_type_config.get("schema_metadata") or {}).get("columns") or []
        column_names = [c["name"] for c in metadata_columns]
        assert column_names == ["id", "new_column"]

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_writes_metadata_for_new_other_schema_table_after_schema_cleared(self, mock_get_source):
        # Scenario reported by users:
        #   1. Source created on master with `job_inputs={schema: "public"}` — limits sync to the
        #      `public` namespace. Legacy `example_table` row has no schema_metadata.
        #   2. After upgrading to this PR the user clears `job_inputs.schema`, expecting to enable
        #      tables from other Postgres schemas (e.g. `poblic`).
        #   3. Refresh runs, discovery returns both `public.example_table` and `poblic.example_table`.
        #
        # The new `poblic.example_table` row MUST carry schema_metadata pointing at `poblic`/
        # `example_table`, otherwise source_for_pipeline falls back to `config.schema or "public"`
        # and emits `FROM "public"."poblic.example_table"` — a non-existent relation.
        mock_get_source.return_value.parse_config.return_value = None
        mock_get_source.return_value.get_version_deprecation.return_value = None
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="legacy",
            access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
            job_inputs={"host": "localhost", "port": 5432, "schema": ""},  # cleared
        )
        ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source_id=source.pk,
            name="example_table",
            should_sync=True,
        )

        mock_get_source.return_value.get_schemas.return_value = [
            SourceSchema(
                name="public.example_table",
                supports_incremental=False,
                supports_append=False,
                columns=[("id", "integer", False)],
                foreign_keys=[],
                source_schema="public",
                source_table_name="example_table",
            ),
            SourceSchema(
                name="poblic.example_table",
                supports_incremental=False,
                supports_append=False,
                columns=[("id", "integer", False)],
                foreign_keys=[],
                source_schema="poblic",
                source_table_name="example_table",
            ),
        ]
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )
        assert response.status_code == status.HTTP_200_OK, response.content

        # `rename_postgres_schemas_to_match_source_schemas` matches the legacy unqualified
        # row by location to the discovered `public.example_table` (legacy falls back to "public"
        # when no default schema is set), then `consolidate_postgres_legacy_rows` qualifies the
        # legacy row in place using the pinned `source_schema`. `s3_folder_name="example_table"`
        # keeps the Delta path anchored to the legacy folder so no data is orphaned.
        legacy = ExternalDataSchema.objects.get(team_id=self.team.pk, source_id=source.pk, name="public.example_table")
        legacy_metadata = legacy.sync_type_config.get("schema_metadata") or {}
        assert legacy_metadata.get("source_schema") == "public"
        assert legacy_metadata.get("source_table_name") == "example_table"
        assert legacy.s3_folder_name == "example_table"
        # The unqualified row is gone — it was renamed in place.
        assert not ExternalDataSchema.objects.filter(
            team_id=self.team.pk, source_id=source.pk, name="example_table", deleted=False
        ).exists()

        # The other discovered table from a different schema becomes its own brand-new row.
        new_row = ExternalDataSchema.objects.get(team_id=self.team.pk, source_id=source.pk, name="poblic.example_table")
        new_metadata = new_row.sync_type_config.get("schema_metadata") or {}
        assert new_metadata.get("source_schema") == "poblic", (
            f"source_for_pipeline would emit SELECT FROM public.poblic.example_table "
            f"(found source_schema={new_metadata.get('source_schema')!r})"
        )
        assert new_metadata.get("source_table_name") == "example_table"

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_clearing_postgres_schema_pins_legacy_rows_to_old_default_schema(self, mock_get_source):
        # Repro for "lost data after clearing schema". Source had schema=poblic, legacy unqualified
        # rows were synced from poblic.<name>. When user clears the schema field, the next refresh
        # would otherwise reanchor those rows to "public" (the static fallback) and orphan their
        # existing Delta data. Pin metadata to the OLD schema before saving the cleared config so
        # the rename helper can match correctly.
        from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
            PostgresSourceConfig,
        )

        source_mock = mock_get_source.return_value
        parsed_config = Mock(spec=PostgresSourceConfig)
        parsed_config.schema = ""
        parsed_config.to_dict.return_value = {
            "host": "db.example.com",
            "port": 5432,
            "database": "db",
            "user": "u",
            "password": "p",
            "schema": "",
        }
        source_mock.parse_config.return_value = parsed_config
        source_mock.get_version_deprecation.return_value = None
        source_mock.validate_config.return_value = (True, [])
        source_mock.validate_credentials_for_access_method.return_value = (True, None)
        source_mock.validate_credentials.return_value = (True, None)

        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="legacy",
            access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
            job_inputs={
                "host": "db.example.com",
                "port": 5432,
                "database": "db",
                "user": "u",
                "password": "p",
                "schema": "poblic",
            },
        )
        ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source_id=source.pk,
            name="example_table",
            should_sync=True,
        )

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={
                "job_inputs": {
                    "host": "db.example.com",
                    "port": 5432,
                    "database": "db",
                    "user": "u",
                    "password": "p",
                    "schema": "",
                },
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.content

        # Row is renamed to the qualified form so it lives alongside newly-discovered tables from
        # other schemas (e.g. public.example_table) without colliding on the unqualified name.
        legacy = ExternalDataSchema.objects.get(team_id=self.team.pk, source_id=source.pk, name="poblic.example_table")
        metadata = legacy.sync_type_config.get("schema_metadata") or {}
        assert metadata.get("source_schema") == "poblic", (
            f"legacy row pinned to wrong schema: {metadata.get('source_schema')!r}"
        )
        assert metadata.get("source_table_name") == "example_table"
        # s3_folder_name pins the Delta path to the legacy "example_table" folder so existing data
        # stays in place — no rewrite, no orphan.
        assert legacy.s3_folder_name == "example_table"
        # The original unqualified row is gone (it was renamed in place).
        assert not ExternalDataSchema.objects.filter(
            team_id=self.team.pk, source_id=source.pk, name="example_table", deleted=False
        ).exists()

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_clearing_postgres_schema_drops_duplicate_qualified_row(self, mock_get_source):
        # A prior refresh (before this migration landed) might have created `poblic.example_table`
        # as a separate row. When the user clears the schema, the legacy unqualified row gets
        # renamed to that qualified form — the orphan duplicate must be soft-deleted so the legacy
        # row (with the actual Delta data) is canonical.
        from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
            PostgresSourceConfig,
        )

        source_mock = mock_get_source.return_value
        parsed_config = Mock(spec=PostgresSourceConfig)
        parsed_config.schema = ""
        parsed_config.to_dict.return_value = {
            "host": "h",
            "port": 5432,
            "database": "db",
            "user": "u",
            "password": "p",
            "schema": "",
        }
        source_mock.parse_config.return_value = parsed_config
        source_mock.get_version_deprecation.return_value = None
        source_mock.validate_config.return_value = (True, [])
        source_mock.validate_credentials_for_access_method.return_value = (True, None)
        source_mock.validate_credentials.return_value = (True, None)

        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="dup",
            access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
            job_inputs={
                "host": "h",
                "port": 5432,
                "database": "db",
                "user": "u",
                "password": "p",
                "schema": "poblic",
            },
        )
        live_table = DataWarehouseTable.objects.create(
            name="duppostgres_example_table",
            format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            team=self.team,
            url_pattern="https://bucket/team_X_postgres_example_table/*",
            external_data_source=source,
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64"}},
        )
        live = ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source_id=source.pk,
            name="example_table",
            should_sync=True,
            table=live_table,
        )
        orphan = ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source_id=source.pk,
            name="poblic.example_table",
            should_sync=False,
        )

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={
                "job_inputs": {
                    "host": "h",
                    "port": 5432,
                    "database": "db",
                    "user": "u",
                    "password": "p",
                    "schema": "",
                },
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.content

        # The legacy row absorbs the qualified name and keeps its DataWarehouseTable link.
        live.refresh_from_db()
        assert live.name == "poblic.example_table"
        assert live.table_id == live_table.id
        assert live.s3_folder_name == "example_table"
        # The orphan duplicate is soft-deleted.
        orphan.refresh_from_db()
        assert orphan.deleted is True

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_persists_detected_primary_key_for_cdc(self, mock_get_source):
        # A table added after source creation is discovered via refresh. Its detected primary key
        # must be persisted to sync_type_config.primary_key_columns so it can later be switched to
        # CDC (which requires a PK) — otherwise the toggle fails with "refresh to pick one up".
        mock_get_source.return_value.parse_config.return_value = None
        mock_get_source.return_value.get_version_deprecation.return_value = None
        mock_get_source.return_value.get_schemas.return_value = [
            SourceSchema(
                name="public.cdc_test_orders",
                supports_incremental=False,
                supports_append=False,
                columns=[("id", "integer", False), ("customer", "text", False)],
                foreign_keys=[],
                source_schema="public",
                source_table_name="cdc_test_orders",
                detected_primary_keys=["id"],
            ),
        ]
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
            job_inputs={"host": "localhost", "port": 5432, "schema": "public"},
        )
        schema = ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source_id=source.pk,
            name="public.cdc_test_orders",
            should_sync=False,
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )
        assert response.status_code == status.HTTP_200_OK, response.content

        schema.refresh_from_db()
        assert schema.sync_type_config.get("primary_key_columns") == ["id"]
        assert schema.primary_key_columns == ["id"]

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_does_not_clobber_existing_primary_key(self, mock_get_source):
        # A user-set / previously-stored PK must survive refresh even if discovery detects a
        # different one — the explicit choice wins.
        mock_get_source.return_value.parse_config.return_value = None
        mock_get_source.return_value.get_version_deprecation.return_value = None
        mock_get_source.return_value.get_schemas.return_value = [
            SourceSchema(
                name="public.orders",
                supports_incremental=False,
                supports_append=False,
                columns=[("id", "integer", False), ("order_key", "text", False)],
                foreign_keys=[],
                source_schema="public",
                source_table_name="orders",
                detected_primary_keys=["id"],
            ),
        ]
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
            job_inputs={"host": "localhost", "port": 5432, "schema": "public"},
        )
        schema = ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source_id=source.pk,
            name="public.orders",
            should_sync=False,
            sync_type_config={"primary_key_columns": ["order_key"]},
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )
        assert response.status_code == status.HTTP_200_OK, response.content

        schema.refresh_from_db()
        assert schema.sync_type_config.get("primary_key_columns") == ["order_key"]
