from __future__ import annotations

from typing import cast

import pytest
from posthog.test.base import BaseTest
from unittest import mock

from posthog.schema import DatabaseSchemaManagedWarehousePromotedTable

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.managed_warehouse_postgres_table import ManagedWarehousePostgresTable

from products.data_warehouse.backend.models import DataWarehouseTable, ManagedWarehousePromotedTable

pytestmark = [pytest.mark.django_db]


class _FakeDuckgresServer:
    host = "duckgres.example.com"
    port = 5432
    database = "ducklake"
    username = "warehouse_user"
    password = "s3cret"


class TestDatabaseSerializeManagedWarehouse(BaseTest):
    @mock.patch("posthog.ducklake.common.get_duckgres_server_for_organization")
    @mock.patch("posthog.ducklake.common._get_org_id_for_team")
    def test_managed_warehouse_table_appears_under_dedicated_schema_type(self, mock_org_id, mock_get_server):
        mock_org_id.return_value = "org-123"
        mock_get_server.return_value = _FakeDuckgresServer()

        promoted = ManagedWarehousePromotedTable.objects.create(
            team=self.team, source_schema_name="public", source_table_name="users"
        )
        DataWarehouseTable.objects.create(
            team=self.team,
            name="public.users",
            format=DataWarehouseTable.TableFormat.ManagedWarehouse,
            url_pattern="",
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True}},
            managed_warehouse_promoted_table=promoted,
        )

        database = Database.create_for(team=self.team)
        serialized = database.serialize(HogQLContext(team_id=self.team.pk, database=database))

        # The serialized table is the managed-warehouse type, not the regular data-warehouse type.
        entry = serialized.get("public.users")
        assert entry is not None
        managed = cast(DatabaseSchemaManagedWarehousePromotedTable, entry)
        assert managed.type == "managed_warehouse"
        assert managed.source_schema_name == "public"
        assert managed.source_table_name == "users"
        assert "id" in managed.fields

    @mock.patch("posthog.ducklake.common.get_duckgres_server_for_organization")
    @mock.patch("posthog.ducklake.common._get_org_id_for_team")
    def test_managed_warehouse_table_added_to_dedicated_section(self, mock_org_id, mock_get_server):
        mock_org_id.return_value = "org-123"
        mock_get_server.return_value = _FakeDuckgresServer()

        promoted = ManagedWarehousePromotedTable.objects.create(
            team=self.team, source_schema_name="analytics", source_table_name="events"
        )
        DataWarehouseTable.objects.create(
            team=self.team,
            name="analytics.events",
            format=DataWarehouseTable.TableFormat.ManagedWarehouse,
            url_pattern="",
            columns={},
            managed_warehouse_promoted_table=promoted,
        )

        database = Database.create_for(team=self.team)

        # Lives in the dedicated section, not the generic warehouse list.
        managed_names = database.get_managed_warehouse_table_names()
        assert "analytics.events" in managed_names

    @mock.patch("posthog.ducklake.common.get_duckgres_server_for_organization")
    @mock.patch("posthog.ducklake.common._get_org_id_for_team")
    def test_managed_warehouse_table_routes_to_postgresql_function_call(self, mock_org_id, mock_get_server):
        mock_org_id.return_value = "org-123"
        mock_get_server.return_value = _FakeDuckgresServer()

        promoted = ManagedWarehousePromotedTable.objects.create(
            team=self.team, source_schema_name="public", source_table_name="users"
        )
        DataWarehouseTable.objects.create(
            team=self.team,
            name="public.users",
            format=DataWarehouseTable.TableFormat.ManagedWarehouse,
            url_pattern="",
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True}},
            managed_warehouse_promoted_table=promoted,
        )

        database = Database.create_for(team=self.team)
        table = database.get_table("public.users")
        assert isinstance(table, ManagedWarehousePostgresTable)

        context = HogQLContext(team_id=self.team.pk)
        rendered = table.to_printed_clickhouse(context)
        assert rendered.startswith("postgresql(")
        # Credentials never inlined.
        assert "duckgres.example.com" not in rendered
        assert "s3cret" not in rendered
