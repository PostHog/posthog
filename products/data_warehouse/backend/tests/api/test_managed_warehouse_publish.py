from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.db import IntegrityError

import psycopg
from parameterized import parameterized
from rest_framework import status
from temporalio.exceptions import WorkflowAlreadyStartedError

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery, Node, NodeType
from products.managed_warehouse.backend.facade import api as managed_warehouse
from products.managed_warehouse.backend.facade.contracts import (
    DuckLakeQueryResult,
    DucklingTables,
    ManagedWarehousePublishedTableRecord,
    ManagedWarehousePublishedTableStatus,
)
from products.managed_warehouse.backend.facade.testing import create_managed_warehouse_published_table_for_test
from products.warehouse_sources.backend.facade.models import DataWarehouseTable

_LOGIC = "products.data_warehouse.backend.logic.managed_warehouse_publish"
_MANAGED_WAREHOUSE_FACADE = "products.managed_warehouse.backend.facade.api"


class TestManagedWarehousePublish(APIBaseTest):
    def _base(self) -> str:
        return f"/api/environments/{self.team.pk}/data_warehouse"

    def _model_schema(self) -> str:
        return f"posthog_data_modeling_team_{self.team.pk}"

    def _publication(
        self,
        *,
        source_schema_name: str | None = None,
        source_table_name: str = "customer_arr",
        name: str = "customer_arr",
        table_id: UUID | None = None,
    ) -> ManagedWarehousePublishedTableRecord:
        return create_managed_warehouse_published_table_for_test(
            team_id=self.team.pk,
            source_schema_name=source_schema_name or self._model_schema(),
            source_table_name=source_table_name,
            name=name,
            table_id=table_id,
        )

    @patch(
        f"{_LOGIC}.resolve_events_persons_tables",
        return_value=DucklingTables(events_table="events", persons_table="persons"),
    )
    @patch(f"{_LOGIC}.execute_ducklake_query")
    def test_modeled_tables_excludes_posthog_managed(
        self, mock_query: MagicMock, _mock_reserved_tables: MagicMock
    ) -> None:
        mock_query.return_value = DuckLakeQueryResult(
            columns=["table_schema", "table_name"],
            types=[],
            results=[
                [self._model_schema(), "customer_arr"],
                [f"posthog_data_modeling_team_{self.team.pk + 1}", "sibling_model"],
                ["posthog_data_imports_team_1", "stripe_invoice"],
                ["shadow_1_models", "model_a"],
                [self._model_schema(), "_posthog_source_batch_duckgres_apply"],
                ["system", "query_log"],
            ],
            sql="",
        )
        response = self.client.get(f"{self._base()}/managed-warehouse-modeled-tables/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == [{"schema_name": self._model_schema(), "table_name": "customer_arr"}]

    @patch(f"{_LOGIC}.execute_ducklake_query")
    @patch(f"{_MANAGED_WAREHOUSE_FACADE}.is_dev_mode", return_value=False)
    @patch(f"{_MANAGED_WAREHOUSE_FACADE}.has_provisioned_warehouse", return_value=False)
    def test_modeled_tables_returns_empty_without_a_provisioned_warehouse(
        self,
        _mock_provisioned: MagicMock,
        _mock_dev_mode: MagicMock,
        mock_query: MagicMock,
    ) -> None:
        response = self.client.get(f"{self._base()}/managed-warehouse-modeled-tables/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"results": []}
        mock_query.assert_not_called()

    @patch(
        f"{_LOGIC}.resolve_events_persons_tables",
        return_value=DucklingTables(events_table="events", persons_table="persons"),
    )
    @patch(f"{_LOGIC}.execute_ducklake_query", side_effect=psycopg.OperationalError("connection timed out"))
    def test_modeled_tables_reports_temporary_unavailability(
        self, _mock_query: MagicMock, _mock_reserved_tables: MagicMock
    ) -> None:
        response = self.client.get(f"{self._base()}/managed-warehouse-modeled-tables/")

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json() == {"detail": "The managed warehouse is temporarily unavailable."}

    @patch(f"{_LOGIC}.start_publish_workflow")
    def test_publish_creates_publication_and_starts_workflow(self, mock_start: MagicMock) -> None:
        response = self.client.post(
            f"{self._base()}/managed-warehouse-publish-table/",
            {"source_schema_name": self._model_schema(), "source_table_name": "customer_arr"},
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        publications = managed_warehouse.list_managed_warehouse_published_tables(self.team.pk)
        assert len(publications) == 1
        publication = publications[0]
        assert publication.name == f"{self._model_schema()}_customer_arr"
        assert publication.status == ManagedWarehousePublishedTableStatus.PENDING
        assert publication.saved_query_id is not None
        saved_query = DataWarehouseSavedQuery.objects.get(team_id=self.team.pk, id=publication.saved_query_id)
        assert saved_query.origin == DataWarehouseSavedQuery.Origin.MANAGED_WAREHOUSE
        assert saved_query.is_materialized is True
        assert saved_query.query == {
            "kind": "ManagedWarehouseSource",
            "source_schema_name": self._model_schema(),
            "source_table_name": "customer_arr",
        }
        assert Node.objects.get(team_id=self.team.pk, saved_query=saved_query).type == NodeType.MAT_VIEW
        mock_start.assert_called_once_with(publication)

    @patch(f"{_LOGIC}.start_publish_workflow")
    def test_publish_rejects_duplicate_warehouse_table_name(self, mock_start: MagicMock) -> None:
        DataWarehouseTable.objects.create(
            team_id=self.team.pk,
            name=f"{self._model_schema()}_customer_arr",
            format=DataWarehouseTable.TableFormat.Parquet,
            url_pattern="s3://x",
        )
        response = self.client.post(
            f"{self._base()}/managed-warehouse-publish-table/",
            {"source_schema_name": self._model_schema(), "source_table_name": "customer_arr"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_start.assert_not_called()

    @parameterized.expand(
        [
            ("invalid_identifier", "main; drop table"),
            ("sibling_project", "posthog_data_modeling_team_999999"),
        ]
    )
    @patch(f"{_LOGIC}.start_publish_workflow")
    def test_publish_rejects_invalid_source(self, _name: str, source_schema_name: str, mock_start: MagicMock) -> None:
        response = self.client.post(
            f"{self._base()}/managed-warehouse-publish-table/",
            {"source_schema_name": source_schema_name, "source_table_name": "x"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_start.assert_not_called()

    @patch(f"{_LOGIC}.start_publish_workflow")
    def test_publish_returns_bad_request_when_concurrent_create_wins(self, mock_start: MagicMock) -> None:
        with patch(
            f"{_MANAGED_WAREHOUSE_FACADE}.create_managed_warehouse_published_table",
            side_effect=IntegrityError("duplicate key"),
        ):
            response = self.client.post(
                f"{self._base()}/managed-warehouse-publish-table/",
                {"source_schema_name": self._model_schema(), "source_table_name": "customer_arr"},
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_start.assert_not_called()

    def test_list_published_tables(self) -> None:
        self._publication(name="z_customer_arr")
        self._publication(name="a_customer_arr", source_table_name="another_table")
        response = self.client.get(f"{self._base()}/managed-warehouse-published-tables/")
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert [result["name"] for result in results] == ["a_customer_arr", "z_customer_arr"]
        assert results[0]["status"] == "pending"

    @patch(f"{_LOGIC}.start_publish_workflow")
    def test_republish_starts_workflow(self, mock_start: MagicMock) -> None:
        publication = self._publication()
        response = self.client.post(
            f"{self._base()}/managed-warehouse-republish-table/",
            {"id": str(publication.id)},
        )
        assert response.status_code == status.HTTP_200_OK
        mock_start.assert_called_once_with(publication)

    @patch(f"{_LOGIC}.start_publish_workflow")
    def test_republish_reports_an_active_workflow(self, mock_start: MagicMock) -> None:
        publication = self._publication()
        mock_start.side_effect = WorkflowAlreadyStartedError("duckgres-publish-table", str(publication.id))

        response = self.client.post(
            f"{self._base()}/managed-warehouse-republish-table/",
            {"id": str(publication.id)},
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json() == {"detail": "A publish for this table is already running."}

    @patch(f"{_LOGIC}.start_snapshot_prune_workflow")
    def test_delete_soft_deletes_publication_and_table(self, mock_prune: MagicMock) -> None:
        table = DataWarehouseTable.objects.create(
            team_id=self.team.pk,
            name="customer_arr",
            format=DataWarehouseTable.TableFormat.Parquet,
            url_pattern="s3://x",
        )
        publication = self._publication(table_id=table.id)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.delete(f"{self._base()}/managed-warehouse-published-table/?id={publication.id}")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        refreshed_publication = managed_warehouse.get_managed_warehouse_published_table(self.team.pk, publication.id)
        table.refresh_from_db()
        assert refreshed_publication is not None
        assert refreshed_publication.deleted is True
        assert table.deleted is True
        assert publication.saved_query_id is not None
        saved_query = DataWarehouseSavedQuery.objects.get(team_id=self.team.pk, id=publication.saved_query_id)
        assert saved_query.deleted is True
        assert not Node.objects.filter(team_id=self.team.pk, saved_query_id=saved_query.id).exists()
        mock_prune.assert_called_once_with(publication)

    @patch(f"{_LOGIC}.start_snapshot_prune_workflow", side_effect=RuntimeError("temporal unavailable"))
    def test_delete_succeeds_when_prune_cannot_be_scheduled(self, _mock_prune: MagicMock) -> None:
        publication = self._publication()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.delete(f"{self._base()}/managed-warehouse-published-table/?id={publication.id}")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        refreshed_publication = managed_warehouse.get_managed_warehouse_published_table(self.team.pk, publication.id)
        assert refreshed_publication is not None
        assert refreshed_publication.deleted is True
