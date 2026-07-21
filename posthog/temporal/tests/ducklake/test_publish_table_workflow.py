from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.ducklake.models import ManagedWarehousePublishedTable
from posthog.temporal.ducklake.publish_table_workflow import (
    PublishMarkFailedInputs,
    PublishRegisterInputs,
    publish_table_mark_failed_activity,
    publish_table_register_activity,
)

from products.warehouse_sources.backend.facade.models import DataWarehouseTable

_FAKE_COLUMNS = {"id": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField", "valid": True}}
_WORKFLOW_MODULE = "posthog.temporal.ducklake.publish_table_workflow"


class TestPublishTableActivities(BaseTest):
    def _publication(self) -> ManagedWarehousePublishedTable:
        return ManagedWarehousePublishedTable.objects.for_team(self.team.pk).create(
            team=self.team,
            source_schema_name="main",
            source_table_name="customer_arr",
            name="customer_arr",
        )

    def test_register_creates_table_and_completes_publication(self) -> None:
        publication = self._publication()

        with (
            patch(f"{_WORKFLOW_MODULE}.close_old_connections"),
            patch.object(DataWarehouseTable, "get_columns", return_value=_FAKE_COLUMNS),
        ):
            publish_table_register_activity(
                PublishRegisterInputs(
                    team_id=self.team.pk,
                    publication_id=str(publication.id),
                    folder_version="20260720120000",
                    row_count=5,
                )
            )

        publication.refresh_from_db()
        assert publication.status == ManagedWarehousePublishedTable.Status.COMPLETED
        assert publication.folder_version == "20260720120000"
        assert publication.last_published_at is not None
        assert publication.table_id is not None
        table = DataWarehouseTable.objects.get(team_id=self.team.pk, id=publication.table_id)
        assert table.format == DataWarehouseTable.TableFormat.Parquet
        assert table.name == "customer_arr"
        assert f"team_{self.team.pk}_publish_{publication.id.hex}" in table.url_pattern
        assert "/20260720120000/**.parquet" in table.url_pattern
        assert table.row_count == 5

    def test_register_repoints_existing_table_on_republish(self) -> None:
        publication = self._publication()

        with (
            patch(f"{_WORKFLOW_MODULE}.close_old_connections"),
            patch.object(DataWarehouseTable, "get_columns", return_value=_FAKE_COLUMNS),
        ):
            publish_table_register_activity(
                PublishRegisterInputs(
                    team_id=self.team.pk,
                    publication_id=str(publication.id),
                    folder_version="20260720120000",
                    row_count=5,
                )
            )
            publish_table_register_activity(
                PublishRegisterInputs(
                    team_id=self.team.pk,
                    publication_id=str(publication.id),
                    folder_version="20260721120000",
                    row_count=7,
                )
            )

        publication.refresh_from_db()
        assert DataWarehouseTable.objects.filter(team_id=self.team.pk, name="customer_arr").count() == 1
        assert publication.table_id is not None
        table = DataWarehouseTable.objects.get(team_id=self.team.pk, id=publication.table_id)
        assert "/20260721120000/**.parquet" in table.url_pattern
        assert table.row_count == 7

    def test_register_retry_reuses_table_after_column_introspection_fails(self) -> None:
        publication = self._publication()
        inputs = PublishRegisterInputs(
            team_id=self.team.pk,
            publication_id=str(publication.id),
            folder_version="20260720120000",
            row_count=5,
        )

        with (
            patch(f"{_WORKFLOW_MODULE}.close_old_connections"),
            patch.object(DataWarehouseTable, "get_columns", side_effect=RuntimeError("describe failed")),
            self.assertRaises(RuntimeError),
        ):
            publish_table_register_activity(inputs)

        with (
            patch(f"{_WORKFLOW_MODULE}.close_old_connections"),
            patch.object(DataWarehouseTable, "get_columns", return_value=_FAKE_COLUMNS),
        ):
            publish_table_register_activity(inputs)

        publication.refresh_from_db()
        assert DataWarehouseTable.objects.filter(team_id=self.team.pk, name="customer_arr").count() == 1
        assert publication.status == ManagedWarehousePublishedTable.Status.COMPLETED

    def test_mark_failed_records_error(self) -> None:
        publication = self._publication()

        with patch(f"{_WORKFLOW_MODULE}.close_old_connections"):
            publish_table_mark_failed_activity(
                PublishMarkFailedInputs(
                    team_id=self.team.pk,
                    publication_id=str(publication.id),
                    error="COPY failed: out of memory",
                )
            )

        publication.refresh_from_db()
        assert publication.status == ManagedWarehousePublishedTable.Status.FAILED
        assert publication.last_error == "COPY failed: out of memory"
