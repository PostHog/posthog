import json
import time

from posthog.test.base import BaseTest

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database

from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

TABLE_COUNT = 40
COLUMN_COUNT = 120


class TestDatabaseSchemaPayload(BaseTest):
    def test_shallow_serialization_collapses_payload_for_large_schemas(self):
        # Reproduces the SQL editor lag: a project with many warehouse tables/columns makes the
        # full DatabaseSchemaQuery payload huge. Run with `pytest -s` to see the timings.
        credential = DataWarehouseCredential.objects.create(access_key="key", access_secret="secret", team=self.team)
        columns = {
            f"column_{i}": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}
            for i in range(COLUMN_COUNT)
        }
        DataWarehouseTable.objects.bulk_create(
            DataWarehouseTable(
                name=f"big_table_{i}",
                format="Parquet",
                team=self.team,
                credential=credential,
                url_pattern=f"https://bucket.s3/data_{i}/*",
                columns=columns,
            )
            for i in range(TABLE_COUNT)
        )

        database = Database.create_for(team=self.team, user=self.user)
        context = HogQLContext(team_id=self.team.pk, database=database)

        start = time.perf_counter()
        full = database.serialize(context, include_hidden_posthog_tables=True)
        full_seconds = time.perf_counter() - start

        start = time.perf_counter()
        shallow = database.serialize(context, include_hidden_posthog_tables=True, include_fields=False)
        shallow_seconds = time.perf_counter() - start

        start = time.perf_counter()
        one_table = database.serialize(context, include_only={"big_table_0"}, include_hidden_posthog_tables=True)
        one_table_seconds = time.perf_counter() - start

        full_bytes = len(json.dumps({name: table.model_dump() for name, table in full.items()}))
        shallow_bytes = len(json.dumps({name: table.model_dump() for name, table in shallow.items()}))
        one_table_bytes = len(json.dumps({name: table.model_dump() for name, table in one_table.items()}))

        print(  # noqa: T201
            f"\nDatabaseSchemaQuery payload for {TABLE_COUNT} warehouse tables x {COLUMN_COUNT} columns:"
            f"\n  full:      {full_bytes / 1024:8.1f} KB in {full_seconds * 1000:7.1f} ms"
            f"\n  shallow:   {shallow_bytes / 1024:8.1f} KB in {shallow_seconds * 1000:7.1f} ms"
            f"\n  one table: {one_table_bytes / 1024:8.1f} KB in {one_table_seconds * 1000:7.1f} ms"
        )

        assert set(shallow.keys()) == set(full.keys())
        assert shallow_bytes < full_bytes / 10
        assert one_table_bytes < full_bytes / 10
