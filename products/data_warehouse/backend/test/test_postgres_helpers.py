import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.data_warehouse.backend.postgres_helpers import get_postgres_source_location, reconcile_postgres_schemas
from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.source_management import (
    filter_columns_by_enabled_columns,
    filter_dwh_columns_by_enabled_columns,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema


class TestGetPostgresSourceLocation:
    @parameterized.expand(
        [
            ("whitespace_only_schema", "public.accounts", "   ", (None, "public", "accounts")),
            ("trimmed_schema", "accounts", " public ", (None, "public", "accounts")),
        ]
    )
    def test_normalizes_default_schema_before_inference(
        self, _name: str, schema_name: str, default_schema: str, expected: tuple[str | None, str, str]
    ) -> None:
        assert get_postgres_source_location(schema_name=schema_name, default_schema=default_schema) == expected


class TestFilterColumnsByEnabledColumns:
    columns = [("id", "integer", False), ("email", "text", True), ("name", "text", True), ("secret", "text", True)]

    def test_none_returns_all(self) -> None:
        assert filter_columns_by_enabled_columns(self.columns, None, ["id"]) == self.columns

    def test_empty_keeps_only_pks(self) -> None:
        result = filter_columns_by_enabled_columns(self.columns, [], ["id"])
        names = [name for name, _type, _nullable in result]
        assert names == ["id"]

    def test_subset_excludes_unselected(self) -> None:
        result = filter_columns_by_enabled_columns(self.columns, ["email"], ["id"])
        names = [name for name, _type, _nullable in result]
        # PK retained, secret excluded, source order preserved.
        assert names == ["id", "email"]

    def test_incremental_field_retained(self) -> None:
        result = filter_columns_by_enabled_columns(self.columns, ["email"], ["id"], incremental_field="name")
        names = [name for name, _type, _nullable in result]
        assert "name" in names

    def test_unknown_enabled_column_silently_dropped(self) -> None:
        # Validation lives at the API boundary; helper just intersects with available columns.
        result = filter_columns_by_enabled_columns(self.columns, ["email", "ghost"], ["id"])
        names = [name for name, _type, _nullable in result]
        assert names == ["id", "email"]


class TestFilterDwhColumnsByEnabledColumns:
    dwh_columns = {
        "id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64"},
        "email": {"hogql": "StringDatabaseField", "clickhouse": "String"},
        "updated_at": {"hogql": "DateTimeDatabaseField", "clickhouse": "DateTime"},
        "secret": {"hogql": "StringDatabaseField", "clickhouse": "String"},
    }

    def test_none_returns_all(self) -> None:
        assert filter_dwh_columns_by_enabled_columns(self.dwh_columns, None, ["id"]) == self.dwh_columns

    def test_subset_keeps_pks(self) -> None:
        result = filter_dwh_columns_by_enabled_columns(self.dwh_columns, ["email"], ["id"])
        assert set(result.keys()) == {"id", "email"}

    def test_incremental_field_retained(self) -> None:
        result = filter_dwh_columns_by_enabled_columns(
            self.dwh_columns, ["email"], ["id"], incremental_field="updated_at"
        )
        assert set(result.keys()) == {"id", "email", "updated_at"}

    def test_empty_keeps_only_pks_and_incremental(self) -> None:
        result = filter_dwh_columns_by_enabled_columns(self.dwh_columns, [], ["id"], incremental_field="updated_at")
        assert set(result.keys()) == {"id", "updated_at"}


class TestReconcilePostgresSchemasLockOrder(APIBaseTest):
    def test_updates_rows_in_ascending_id_order_regardless_of_input_order(self) -> None:
        # Two concurrent refreshes touching an overlapping set of these rows must take their row
        # locks in the same order, or they can deadlock (seen in production: "deadlock detected
        # ... while updating tuple ... in relation posthog_externaldataschema"). The source
        # database's own catalog query doesn't guarantee row order, so `source_schemas` can arrive
        # in a different order on each call — reconcile_postgres_schemas must impose its own
        # stable order rather than following it.
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
        schema_a = ExternalDataSchema.objects.create(
            team_id=self.team.pk, source_id=source.pk, name="table_a", should_sync=True
        )
        schema_b = ExternalDataSchema.objects.create(
            team_id=self.team.pk, source_id=source.pk, name="table_b", should_sync=True
        )
        assert schema_a.id < schema_b.id

        # Discovery order is the reverse of row-id order.
        source_schemas = [
            SourceSchema(
                name="table_b", supports_incremental=False, supports_append=False, columns=[("id", "integer", False)]
            ),
            SourceSchema(
                name="table_a", supports_incremental=False, supports_append=False, columns=[("id", "integer", False)]
            ),
        ]

        saved_names: list[str] = []
        original_save = ExternalDataSchema.save

        def _tracking_save(self: ExternalDataSchema, *args, **kwargs):
            saved_names.append(self.name)
            return original_save(self, *args, **kwargs)

        with patch.object(ExternalDataSchema, "save", _tracking_save):
            reconcile_postgres_schemas(source=source, source_schemas=source_schemas, team_id=self.team.pk)

        assert saved_names == ["table_a", "table_b"]
