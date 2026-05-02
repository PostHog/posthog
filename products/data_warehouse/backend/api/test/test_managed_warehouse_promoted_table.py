from __future__ import annotations

import pytest
from posthog.test.base import APIBaseTest
from unittest import mock

from rest_framework import status

from products.data_warehouse.backend.models import DataWarehouseTable, ManagedWarehousePromotedTable

pytestmark = [pytest.mark.django_db]

LIST_URL = "/api/environments/{team_id}/managed_warehouse_promoted_tables/"
DETAIL_URL = "/api/environments/{team_id}/managed_warehouse_promoted_tables/{id}/"
AVAILABLE_URL = "/api/environments/{team_id}/managed_warehouse_promoted_tables/available_source_tables/"


class TestManagedWarehousePromotedTableAPI(APIBaseTest):
    def _list_url(self) -> str:
        return LIST_URL.format(team_id=self.team.id)

    def _detail_url(self, promoted_id: str) -> str:
        return DETAIL_URL.format(team_id=self.team.id, id=promoted_id)

    def _available_url(self) -> str:
        return AVAILABLE_URL.format(team_id=self.team.id)

    def test_list_returns_only_team_rows_and_excludes_soft_deleted(self):
        ManagedWarehousePromotedTable.objects.create(
            team=self.team, source_schema_name="public", source_table_name="users"
        )
        ManagedWarehousePromotedTable.objects.create(
            team=self.team,
            source_schema_name="public",
            source_table_name="hidden",
            deleted=True,
        )

        from posthog.models import Team

        other_team = Team.objects.create(organization=self.organization, name="other")
        ManagedWarehousePromotedTable.objects.create(
            team=other_team, source_schema_name="public", source_table_name="orders"
        )

        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["source_table_name"] == "users"

    @mock.patch("products.data_warehouse.backend.api.managed_warehouse_promoted_table._introspect_columns")
    def test_create_persists_row_and_links_data_warehouse_table(self, mock_introspect):
        mock_introspect.return_value = {
            "id": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField", "valid": True},
            "email": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField", "valid": True},
        }

        response = self.client.post(
            self._list_url(),
            data={"source_schema_name": "public", "source_table_name": "users"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        body = response.json()
        promoted = ManagedWarehousePromotedTable.objects.get(id=body["id"])
        assert promoted.team_id == self.team.id
        assert promoted.created_by_id == self.user.id

        table = DataWarehouseTable.objects.get(managed_warehouse_promoted_table=promoted)
        assert table.format == "ManagedWarehouse"
        assert table.url_pattern == ""
        assert "id" in table.columns
        assert table.columns["id"]["clickhouse"] == "Int64"

        mock_introspect.assert_called_once_with(self.team.id, "public", "users")

    def test_create_rejects_blank_inputs(self):
        response = self.client.post(
            self._list_url(),
            data={"source_schema_name": " ", "source_table_name": "users"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @mock.patch("products.data_warehouse.backend.api.managed_warehouse_promoted_table._introspect_columns")
    def test_create_surfaces_introspection_failures(self, mock_introspect):
        from rest_framework.exceptions import ValidationError as DrfValidationError

        mock_introspect.side_effect = DrfValidationError("connection refused")

        response = self.client.post(
            self._list_url(),
            data={"source_schema_name": "public", "source_table_name": "users"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        # No rows persisted on introspection failure.
        assert ManagedWarehousePromotedTable.objects.filter(team_id=self.team.id).count() == 0

    def test_destroy_soft_deletes_promotion_and_linked_table(self):
        promoted = ManagedWarehousePromotedTable.objects.create(
            team=self.team, source_schema_name="public", source_table_name="users"
        )
        table = DataWarehouseTable.objects.create(
            team=self.team,
            name="managed_warehouse.public.users",
            format=DataWarehouseTable.TableFormat.ManagedWarehouse,
            url_pattern="",
            managed_warehouse_promoted_table=promoted,
        )

        response = self.client.delete(self._detail_url(str(promoted.id)))
        assert response.status_code == status.HTTP_204_NO_CONTENT

        promoted.refresh_from_db()
        table.refresh_from_db()
        assert promoted.deleted is True
        assert table.deleted is True

    @mock.patch("products.data_warehouse.backend.api.managed_warehouse_promoted_table.execute_ducklake_query")
    def test_available_source_tables_lists_with_already_promoted_flag(self, mock_query):
        from posthog.ducklake.client import DuckLakeQueryResult

        mock_query.return_value = DuckLakeQueryResult(
            columns=["table_schema", "table_name", "table_type"],
            types=["text", "text", "text"],
            results=[
                ["public", "users", "BASE TABLE"],
                ["public", "orders", "VIEW"],
                ["analytics", "events", "BASE TABLE"],
                # Defensive Python filter still rejects this even if duckgres returns it.
                ["pg_catalog", "pg_class", "BASE TABLE"],
            ],
            sql="<rendered>",
        )

        ManagedWarehousePromotedTable.objects.create(
            team=self.team, source_schema_name="public", source_table_name="users"
        )
        ManagedWarehousePromotedTable.objects.create(
            team=self.team,
            source_schema_name="analytics",
            source_table_name="events",
            deleted=True,  # soft-deleted: should NOT count as promoted
        )

        response = self.client.get(self._available_url())
        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert len(body) == 3  # pg_catalog row filtered out
        by_key = {(r["schema"], r["name"]): r for r in body}
        assert by_key[("public", "users")]["already_promoted"] is True
        assert by_key[("public", "orders")]["already_promoted"] is False
        assert by_key[("public", "orders")]["table_type"] == "VIEW"
        assert by_key[("analytics", "events")]["already_promoted"] is False

    @mock.patch("products.data_warehouse.backend.api.managed_warehouse_promoted_table.execute_ducklake_query")
    def test_available_source_tables_surfaces_query_errors(self, mock_query):
        mock_query.side_effect = RuntimeError("duckgres unreachable")

        response = self.client.get(self._available_url())
        assert response.status_code == status.HTTP_400_BAD_REQUEST
