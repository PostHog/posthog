from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.ducklake.models import ManagedWarehousePublishedTable
from posthog.ducklake.publish import PUBLISHED_PREFIX, publish_folder
from posthog.temporal.ducklake.publish_table_workflow import (
    PrunePublishedSnapshotInputs,
    PublishMarkFailedInputs,
    PublishRegisterInputs,
    PublishTableInputs,
    prune_published_snapshot_activity,
    publish_table_copy_activity,
    publish_table_mark_failed_activity,
    publish_table_register_activity,
)

from products.warehouse_sources.backend.facade.models import DataWarehouseTable

_FAKE_COLUMNS = {"id": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField", "valid": True}}
_WORKFLOW_MODULE = "posthog.temporal.ducklake.publish_table_workflow"
_BUCKET = "posthog-duckling-acme-mw-prod-us"
_BUCKET_REGION = "us-east-1"


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
                    bucket=_BUCKET,
                    bucket_region=_BUCKET_REGION,
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
        assert f"/{_BUCKET}/__posthog_published/" in table.url_pattern
        assert f"team_{self.team.pk}_publish_{publication.id.hex}" in table.url_pattern
        assert "/20260720120000/**.parquet" in table.url_pattern
        assert table.row_count == 5

    def test_copy_rejects_empty_modeled_table_before_export(self) -> None:
        publication = self._publication()
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.__exit__.return_value = False
        count_cursor = MagicMock()
        count_cursor.fetchone.return_value = (0,)
        connection.execute.side_effect = [count_cursor]

        with (
            patch(f"{_WORKFLOW_MODULE}.close_old_connections"),
            patch(
                f"{_WORKFLOW_MODULE}.get_duckgres_config_for_org",
                return_value={
                    "DUCKGRES_HOST": "duckgres",
                    "DUCKGRES_PORT": "5432",
                    "DUCKGRES_DATABASE": "ducklake",
                    "DUCKGRES_USERNAME": "posthog",
                    "DUCKGRES_PASSWORD": "password",
                },
            ),
            patch(
                f"{_WORKFLOW_MODULE}.get_org_config",
                return_value={"DUCKLAKE_BUCKET": _BUCKET, "DUCKLAKE_BUCKET_REGION": _BUCKET_REGION},
            ),
            patch(f"{_WORKFLOW_MODULE}.psycopg.connect", return_value=connection),
            patch(f"{_WORKFLOW_MODULE}.setup_duckgres_session"),
            patch(f"{_WORKFLOW_MODULE}.HeartbeaterSync"),
            self.assertRaisesRegex(ValueError, "Empty modeled tables cannot be published yet"),
        ):
            publish_table_copy_activity(PublishTableInputs(team_id=self.team.pk, publication_id=str(publication.id)))

        assert connection.execute.call_count == 1

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
                    bucket=_BUCKET,
                    bucket_region=_BUCKET_REGION,
                )
            )
            publish_table_register_activity(
                PublishRegisterInputs(
                    team_id=self.team.pk,
                    publication_id=str(publication.id),
                    folder_version="20260721120000",
                    row_count=7,
                    bucket=_BUCKET,
                    bucket_region=_BUCKET_REGION,
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
            bucket=_BUCKET,
            bucket_region=_BUCKET_REGION,
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

    # Prune is the only thing standing between a deleted publication and a permanent
    # snapshot leak — and between a live table and a deleted-underneath folder.
    @parameterized.expand(
        [
            (
                "deleted_publication_loses_everything",
                True,
                "20260720120000",
                "20260721120000",
                ["20260719120000", "20260720120000", "20260721120000"],
            ),
            (
                "live_publication_keeps_live_and_completed_versions",
                False,
                "20260720120000",
                "20260721120000",
                ["20260719120000"],
            ),
            (
                "failed_first_publish_prunes_partial_attempts",
                False,
                None,
                None,
                ["20260719120000", "20260720120000", "20260721120000"],
            ),
        ]
    )
    def test_prune_published_snapshot(
        self,
        _name: str,
        deleted: bool,
        folder_version: str | None,
        completed_version: str | None,
        expected_deleted_versions: list[str],
    ) -> None:
        publication = self._publication()
        publication.deleted = deleted
        publication.folder_version = folder_version
        publication.save()

        folder = publish_folder(self.team.pk, publication.id.hex)
        versions = ["20260719120000", "20260720120000", "20260721120000"]
        keys = [f"{PUBLISHED_PREFIX}/{folder}/{version}/part-0.parquet" for version in versions]

        with (
            patch(f"{_WORKFLOW_MODULE}.close_old_connections"),
            patch(f"{_WORKFLOW_MODULE}.get_org_config", return_value={"DUCKLAKE_BUCKET": _BUCKET}),
            patch("boto3.client") as mock_boto_client,
        ):
            s3 = mock_boto_client.return_value
            s3.get_paginator.return_value.paginate.return_value = [{"Contents": [{"Key": key} for key in keys]}]

            prune_published_snapshot_activity(
                PrunePublishedSnapshotInputs(
                    team_id=self.team.pk,
                    publication_id=str(publication.id),
                    completed_version=completed_version,
                )
            )

        expected_deleted = [
            f"{PUBLISHED_PREFIX}/{folder}/{version}/part-0.parquet" for version in expected_deleted_versions
        ]
        if expected_deleted:
            s3.delete_objects.assert_called_once_with(
                Bucket=_BUCKET, Delete={"Objects": [{"Key": key} for key in expected_deleted]}
            )
        else:
            s3.delete_objects.assert_not_called()
