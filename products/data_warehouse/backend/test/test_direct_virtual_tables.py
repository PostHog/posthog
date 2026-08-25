from posthog.test.base import APIBaseTest

from posthog.hogql.database.direct_motherduck_table import DirectMotherDuckTable

from products.data_warehouse.backend.direct_virtual_tables import build_direct_table_for_schema
from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

SCHEMA_METADATA = {
    "columns": [
        {"name": "id", "data_type": "integer", "is_nullable": False},
        {"name": "email", "data_type": "varchar(255)", "is_nullable": True},
        {"name": "secret", "data_type": "varchar(255)", "is_nullable": True},
    ]
}


class TestBuildDirectTableForSchema(APIBaseTest):
    def _create(self, *, enabled_columns: list[str] | None) -> tuple[ExternalDataSchema, ExternalDataSource]:
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
            direct_query_enabled=True,
            job_inputs={"host": "h", "port": "5432", "database": "d", "user": "u", "password": "p", "schema": "public"},
        )
        schema = ExternalDataSchema.objects.create(
            name="customers",
            team=self.team,
            source=source,
            enabled_columns=enabled_columns,
            sync_type_config={"schema_metadata": SCHEMA_METADATA, "primary_key_columns": ["id"]},
        )
        return schema, source

    def test_deselected_column_excluded_from_direct_table(self):
        # A user with only "enabled_columns": ["email"] must not be able to read "secret"
        # through the live-query virtual table, even though it's in schema_metadata.
        schema, source = self._create(enabled_columns=["email"])

        table = build_direct_table_for_schema(schema, source)

        assert table is not None
        assert "secret" not in table.fields
        assert "email" in table.fields
        assert "id" in table.fields  # primary key always retained

    def test_none_enabled_columns_syncs_everything(self):
        schema, source = self._create(enabled_columns=None)

        table = build_direct_table_for_schema(schema, source)

        assert table is not None
        assert set(table.fields) == {"id", "email", "secret"}

    def test_motherduck_virtual_table_resolves_location_and_columns(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.MOTHERDUCK,
            access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
            direct_query_enabled=True,
            job_inputs={"access_token": "t", "database": "my_db"},
        )
        schema = ExternalDataSchema.objects.create(
            name="nyc.taxi",
            team=self.team,
            source=source,
            enabled_columns=None,
            sync_type_config={
                "schema_metadata": {
                    "source_catalog": "my_db",
                    "source_schema": "nyc",
                    "source_table_name": "taxi",
                    "columns": [
                        {"name": "id", "data_type": "BIGINT", "is_nullable": False},
                        {"name": "fare", "data_type": "DOUBLE", "is_nullable": True},
                    ],
                },
            },
        )

        table = build_direct_table_for_schema(schema, source)

        assert isinstance(table, DirectMotherDuckTable)
        assert (table.motherduck_database, table.motherduck_schema, table.motherduck_table_name) == (
            "my_db",
            "nyc",
            "taxi",
        )
        assert set(table.fields) == {"id", "fare"}
