from __future__ import annotations

from datetime import timedelta

import pytest
from posthog.test.base import APIBaseTest
from unittest import mock

from parameterized import parameterized
from rest_framework import status

from products.data_warehouse.backend.models import ManagedWarehousePromotedTable

pytestmark = [pytest.mark.django_db]

LIST_URL = "/api/environments/{team_id}/managed_warehouse_promoted_tables/"
DETAIL_URL = "/api/environments/{team_id}/managed_warehouse_promoted_tables/{id}/"
TRIGGER_URL = "/api/environments/{team_id}/managed_warehouse_promoted_tables/{id}/trigger/"


class TestManagedWarehousePromotedTableAPI(APIBaseTest):
    def _list_url(self) -> str:
        return LIST_URL.format(team_id=self.team.id)

    def _detail_url(self, promoted_id: str) -> str:
        return DETAIL_URL.format(team_id=self.team.id, id=promoted_id)

    def _trigger_url(self, promoted_id: str) -> str:
        return TRIGGER_URL.format(team_id=self.team.id, id=promoted_id)

    def test_list_returns_only_team_rows(self):
        ManagedWarehousePromotedTable.objects.create(
            team=self.team, source_schema_name="public", source_table_name="users"
        )

        # Different team - should be filtered out.
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

    def test_list_excludes_soft_deleted(self):
        ManagedWarehousePromotedTable.objects.create(
            team=self.team, source_schema_name="public", source_table_name="users", deleted=True
        )

        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 0

    @mock.patch("products.data_warehouse.backend.api.managed_warehouse_promoted_table.sync_promote_table_schedule")
    def test_create_persists_row_and_creates_schedule(self, mock_sync):
        response = self.client.post(
            self._list_url(),
            data={
                "source_schema_name": "public",
                "source_table_name": "users",
                "sync_frequency": "1hour",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        body = response.json()
        assert body["source_schema_name"] == "public"
        assert body["sync_frequency_interval"] == "1hour"
        assert body["status"] == "pending"

        promoted = ManagedWarehousePromotedTable.objects.get(id=body["id"])
        assert promoted.team_id == self.team.id
        assert promoted.created_by_id == self.user.id
        assert promoted.sync_frequency_interval == timedelta(hours=1)

        mock_sync.assert_called_once()
        _, kwargs = mock_sync.call_args
        assert kwargs == {"create": True, "trigger_immediately": True}

    @parameterized.expand(
        [
            ("5min", timedelta(minutes=5)),
            ("15min", timedelta(minutes=15)),
            ("30min", timedelta(minutes=30)),
            ("1hour", timedelta(hours=1)),
            ("6hour", timedelta(hours=6)),
            ("12hour", timedelta(hours=12)),
            ("24hour", timedelta(hours=24)),
        ]
    )
    @mock.patch("products.data_warehouse.backend.api.managed_warehouse_promoted_table.sync_promote_table_schedule")
    def test_create_supports_all_frequency_options(self, frequency, expected_interval, mock_sync):
        response = self.client.post(
            self._list_url(),
            data={
                "source_schema_name": "s",
                "source_table_name": f"t_{frequency}",
                "sync_frequency": frequency,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.content
        promoted = ManagedWarehousePromotedTable.objects.get(id=response.json()["id"])
        assert promoted.sync_frequency_interval == expected_interval

    @mock.patch("products.data_warehouse.backend.api.managed_warehouse_promoted_table.sync_promote_table_schedule")
    def test_create_rejects_unknown_frequency(self, mock_sync):
        response = self.client.post(
            self._list_url(),
            data={
                "source_schema_name": "s",
                "source_table_name": "t",
                "sync_frequency": "every-tuesday",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_sync.assert_not_called()

    @mock.patch("products.data_warehouse.backend.api.managed_warehouse_promoted_table.sync_promote_table_schedule")
    def test_create_rejects_blank_schema_or_table(self, mock_sync):
        response = self.client.post(
            self._list_url(),
            data={"source_schema_name": " ", "source_table_name": "t", "sync_frequency": "1hour"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_sync.assert_not_called()

    @mock.patch("products.data_warehouse.backend.api.managed_warehouse_promoted_table.sync_promote_table_schedule")
    def test_update_changes_interval_and_resyncs_schedule(self, mock_sync):
        promoted = ManagedWarehousePromotedTable.objects.create(
            team=self.team,
            source_schema_name="s",
            source_table_name="t",
            sync_frequency_interval=timedelta(hours=1),
        )

        response = self.client.patch(
            self._detail_url(str(promoted.id)),
            data={"sync_frequency": "6hour"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        promoted.refresh_from_db()
        assert promoted.sync_frequency_interval == timedelta(hours=6)
        mock_sync.assert_called_once()
        _, kwargs = mock_sync.call_args
        assert kwargs == {"create": False}

    @mock.patch("products.data_warehouse.backend.api.managed_warehouse_promoted_table.sync_promote_table_schedule")
    def test_update_without_frequency_does_not_resync(self, mock_sync):
        promoted = ManagedWarehousePromotedTable.objects.create(
            team=self.team, source_schema_name="s", source_table_name="t"
        )

        # Empty PATCH — should be a no-op as far as Temporal is concerned.
        response = self.client.patch(self._detail_url(str(promoted.id)), data={}, format="json")
        assert response.status_code == status.HTTP_200_OK
        mock_sync.assert_not_called()

    @mock.patch("products.data_warehouse.backend.api.managed_warehouse_promoted_table.delete_promote_table_schedule")
    def test_destroy_soft_deletes_and_removes_schedule(self, mock_delete):
        promoted = ManagedWarehousePromotedTable.objects.create(
            team=self.team, source_schema_name="s", source_table_name="t"
        )

        response = self.client.delete(self._detail_url(str(promoted.id)))
        assert response.status_code == status.HTTP_204_NO_CONTENT

        promoted.refresh_from_db()
        assert promoted.deleted is True
        mock_delete.assert_called_once_with(promoted.schedule_id)

    @mock.patch("products.data_warehouse.backend.api.managed_warehouse_promoted_table.trigger_promote_table_schedule")
    def test_trigger_action_calls_schedule_trigger(self, mock_trigger):
        promoted = ManagedWarehousePromotedTable.objects.create(
            team=self.team, source_schema_name="s", source_table_name="t"
        )

        response = self.client.post(self._trigger_url(str(promoted.id)))

        assert response.status_code == status.HTTP_202_ACCEPTED
        mock_trigger.assert_called_once_with(promoted.schedule_id)

    @mock.patch("products.data_warehouse.backend.api.managed_warehouse_promoted_table.execute_ducklake_query")
    def test_available_source_tables_lists_with_already_promoted_flag(self, mock_query):
        from posthog.ducklake.client import DuckLakeQueryResult

        # The customer has 3 candidate tables and 1 system row that should be filtered out by Python.
        mock_query.return_value = DuckLakeQueryResult(
            columns=["table_schema", "table_name", "table_type"],
            types=["text", "text", "text"],
            results=[
                ["public", "users", "BASE TABLE"],
                ["public", "orders", "VIEW"],
                ["analytics", "events", "BASE TABLE"],
                # Defensive filter: even if duckgres returns a system row, Python rejects it.
                ["pg_catalog", "pg_class", "BASE TABLE"],
            ],
            sql="<rendered sql>",
        )

        # One existing promotion -> already_promoted should be True for that row only.
        ManagedWarehousePromotedTable.objects.create(
            team=self.team, source_schema_name="public", source_table_name="users"
        )
        # A soft-deleted promotion for a different table — should not affect the flag.
        ManagedWarehousePromotedTable.objects.create(
            team=self.team,
            source_schema_name="analytics",
            source_table_name="events",
            deleted=True,
        )

        url = f"/api/environments/{self.team.id}/managed_warehouse_promoted_tables/available_source_tables/"
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        # Three rows after the pg_catalog row is filtered out in Python.
        assert len(body) == 3
        by_key = {(row["schema"], row["name"]): row for row in body}
        assert by_key[("public", "users")]["already_promoted"] is True
        assert by_key[("public", "orders")]["already_promoted"] is False
        assert by_key[("analytics", "events")]["already_promoted"] is False
        assert by_key[("public", "orders")]["table_type"] == "VIEW"
        mock_query.assert_called_once()

    @mock.patch("products.data_warehouse.backend.api.managed_warehouse_promoted_table.execute_ducklake_query")
    def test_available_source_tables_surfaces_query_errors(self, mock_query):
        mock_query.side_effect = RuntimeError("connection refused")

        url = f"/api/environments/{self.team.id}/managed_warehouse_promoted_tables/available_source_tables/"
        response = self.client.get(url)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
