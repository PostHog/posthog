from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.db import IntegrityError

import psycopg
from parameterized import parameterized
from rest_framework import status
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.ducklake.client import DuckLakeQueryResult
from posthog.ducklake.models import ManagedWarehousePublishedTable

from products.warehouse_sources.backend.facade.models import DataWarehouseTable

_LOGIC = "products.data_warehouse.backend.logic.managed_warehouse_publish"


class TestManagedWarehousePublish(APIBaseTest):
    def _base(self) -> str:
        return f"/api/environments/{self.team.pk}/data_warehouse"

    def _publication(self, **overrides: object) -> ManagedWarehousePublishedTable:
        defaults: dict[str, object] = {
            "team": self.team,
            "source_schema_name": "main",
            "source_table_name": "customer_arr",
            "name": "customer_arr",
        }
        defaults.update(overrides)
        return ManagedWarehousePublishedTable.objects.for_team(self.team.pk).create(**defaults)

    @patch(f"{_LOGIC}.resolve_events_persons_tables", return_value=("events", "persons"))
    @patch(f"{_LOGIC}.execute_ducklake_query")
    def test_modeled_tables_excludes_posthog_managed(
        self, mock_query: MagicMock, _mock_reserved_tables: MagicMock
    ) -> None:
        mock_query.return_value = DuckLakeQueryResult(
            columns=["table_schema", "table_name"],
            types=[],
            results=[
                ["main", "customer_arr"],
                ["posthog_data_imports_team_1", "stripe_invoice"],
                ["shadow_1_models", "model_a"],
                ["main", "_posthog_source_batch_duckgres_apply"],
                ["system", "query_log"],
            ],
            sql="",
        )
        response = self.client.get(f"{self._base()}/managed-warehouse-modeled-tables/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == [{"schema_name": "main", "table_name": "customer_arr"}]

    @patch(f"{_LOGIC}.execute_ducklake_query")
    @patch(f"{_LOGIC}.is_dev_mode", return_value=False)
    @patch(f"{_LOGIC}.get_duckgres_server_by_team_org", return_value=None)
    def test_modeled_tables_returns_empty_without_a_provisioned_warehouse(
        self,
        _mock_server: MagicMock,
        _mock_dev_mode: MagicMock,
        mock_query: MagicMock,
    ) -> None:
        response = self.client.get(f"{self._base()}/managed-warehouse-modeled-tables/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"results": []}
        mock_query.assert_not_called()

    @patch(f"{_LOGIC}.resolve_events_persons_tables", return_value=("events", "persons"))
    @patch(f"{_LOGIC}.execute_ducklake_query", side_effect=psycopg.OperationalError("connection timed out"))
    def test_modeled_tables_reports_temporary_unavailability(
        self, _mock_query: MagicMock, _mock_reserved_tables: MagicMock
    ) -> None:
        response = self.client.get(f"{self._base()}/managed-warehouse-modeled-tables/")

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json() == {"detail": "The managed warehouse is temporarily unavailable."}

    @patch(f"{_LOGIC}.start_new_publication")
    def test_publish_creates_publication_and_starts_workflow(self, mock_start: MagicMock) -> None:
        response = self.client.post(
            f"{self._base()}/managed-warehouse-publish-table/",
            {"source_schema_name": "main", "source_table_name": "customer_arr"},
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        publication = ManagedWarehousePublishedTable.objects.for_team(self.team.pk).get()
        assert publication.name == "main_customer_arr"
        assert publication.status == ManagedWarehousePublishedTable.Status.PENDING
        mock_start.assert_called_once_with(publication)

    @patch(f"{_LOGIC}.start_new_publication")
    def test_publish_rejects_duplicate_warehouse_table_name(self, mock_start: MagicMock) -> None:
        DataWarehouseTable.objects.create(
            team_id=self.team.pk,
            name="main_customer_arr",
            format=DataWarehouseTable.TableFormat.Parquet,
            url_pattern="s3://x",
        )
        response = self.client.post(
            f"{self._base()}/managed-warehouse-publish-table/",
            {"source_schema_name": "main", "source_table_name": "customer_arr"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_start.assert_not_called()

    @patch(f"{_LOGIC}.start_new_publication")
    def test_publish_rejects_invalid_identifier(self, mock_start: MagicMock) -> None:
        response = self.client.post(
            f"{self._base()}/managed-warehouse-publish-table/",
            {"source_schema_name": "main; drop table", "source_table_name": "x"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_start.assert_not_called()

    @patch(f"{_LOGIC}.start_new_publication")
    def test_publish_returns_bad_request_when_concurrent_create_wins(self, mock_start: MagicMock) -> None:
        publication_manager = MagicMock()
        publication_manager.filter.return_value.exists.return_value = False
        publication_manager.create.side_effect = IntegrityError("duplicate key")

        with patch.object(
            ManagedWarehousePublishedTable.objects,
            "for_team",
            return_value=publication_manager,
        ):
            response = self.client.post(
                f"{self._base()}/managed-warehouse-publish-table/",
                {"source_schema_name": "main", "source_table_name": "customer_arr"},
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_start.assert_not_called()

    @patch(f"{_LOGIC}.start_publish_workflow", side_effect=RuntimeError("temporal unavailable"))
    def test_publish_reports_a_schedule_failure(self, _mock_start: MagicMock) -> None:
        response = self.client.post(
            f"{self._base()}/managed-warehouse-publish-table/",
            {"source_schema_name": "main", "source_table_name": "customer_arr"},
        )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json() == {"detail": "The publish could not be started. Try again."}
        publication = ManagedWarehousePublishedTable.objects.for_team(self.team.pk).get()
        assert publication.status == ManagedWarehousePublishedTable.Status.FAILED

    def test_list_published_tables(self) -> None:
        table = DataWarehouseTable.objects.create(
            team_id=self.team.pk,
            name="a_customer_arr",
            format=DataWarehouseTable.TableFormat.Parquet,
            url_pattern="s3://x",
        )
        self._publication(name="z_customer_arr")
        self._publication(name="a_customer_arr", source_table_name="another_table", table_id=table.id)
        response = self.client.get(f"{self._base()}/managed-warehouse-published-tables/")
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert [result["name"] for result in results] == ["a_customer_arr", "z_customer_arr"]
        assert results[0]["status"] == "pending"
        assert results[0]["table_id"] == str(table.id)
        assert results[1]["table_id"] is None

    @patch(f"{_LOGIC}.start_publish_workflow")
    def test_republish_starts_workflow(self, mock_start: MagicMock) -> None:
        publication = self._publication(
            status=ManagedWarehousePublishedTable.Status.COMPLETED,
            last_error="Previous failure",
        )
        response = self.client.post(
            f"{self._base()}/managed-warehouse-republish-table/",
            {"id": str(publication.id)},
        )
        assert response.status_code == status.HTTP_200_OK
        mock_start.assert_called_once_with(publication)
        publication.refresh_from_db()
        assert publication.status == ManagedWarehousePublishedTable.Status.PENDING
        assert publication.last_error is None
        assert response.json()["status"] == "pending"

    @parameterized.expand(
        [
            ManagedWarehousePublishedTable.Status.PENDING,
            ManagedWarehousePublishedTable.Status.PUBLISHING,
        ]
    )
    @patch(f"{_LOGIC}.start_publish_workflow")
    def test_republish_rejects_an_active_publication(self, publication_status: str, mock_start: MagicMock) -> None:
        publication = self._publication(status=publication_status)

        response = self.client.post(
            f"{self._base()}/managed-warehouse-republish-table/",
            {"id": str(publication.id)},
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json() == {"detail": "A publish for this table is already running."}
        mock_start.assert_not_called()

    @patch(f"{_LOGIC}.start_publish_workflow")
    def test_republish_reports_a_temporal_workflow_race(self, mock_start: MagicMock) -> None:
        publication = self._publication(status=ManagedWarehousePublishedTable.Status.COMPLETED)
        mock_start.side_effect = WorkflowAlreadyStartedError("duckgres-publish-table", str(publication.id))

        response = self.client.post(
            f"{self._base()}/managed-warehouse-republish-table/",
            {"id": str(publication.id)},
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        publication.refresh_from_db()
        assert publication.status == ManagedWarehousePublishedTable.Status.PENDING

    @patch(f"{_LOGIC}.start_publish_workflow", side_effect=RuntimeError("temporal unavailable"))
    def test_republish_marks_a_schedule_failure_as_failed(self, _mock_start: MagicMock) -> None:
        publication = self._publication(status=ManagedWarehousePublishedTable.Status.COMPLETED)

        response = self.client.post(
            f"{self._base()}/managed-warehouse-republish-table/",
            {"id": str(publication.id)},
        )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json() == {"detail": "The publish could not be started. Try again."}
        publication.refresh_from_db()
        assert publication.status == ManagedWarehousePublishedTable.Status.FAILED
        assert publication.last_error == "temporal unavailable"

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
        publication.refresh_from_db()
        table.refresh_from_db()
        assert publication.deleted is True
        assert table.deleted is True
        mock_prune.assert_called_once_with(publication)

    @patch(f"{_LOGIC}.start_snapshot_prune_workflow", side_effect=RuntimeError("temporal unavailable"))
    def test_delete_succeeds_when_prune_cannot_be_scheduled(self, _mock_prune: MagicMock) -> None:
        publication = self._publication()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.delete(f"{self._base()}/managed-warehouse-published-table/?id={publication.id}")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        publication.refresh_from_db()
        assert publication.deleted is True
