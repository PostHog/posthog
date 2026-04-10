import uuid

from posthog.test.base import BaseTest
from unittest.mock import patch

from dlt.common.normalizers.naming.snake_case import NamingConvention

from posthog.temporal.data_imports.pipelines.helpers import build_table_name
from posthog.temporal.data_imports.pipelines.pipeline_sync import merge_columns

from products.data_warehouse.backend.models import (
    DataWarehouseTable,
    ExternalDataJob,
    ExternalDataSchema,
    ExternalDataSource,
)


def _register_companion_sync(
    run_id: str,
    team_id: int,
    schema_id: uuid.UUID,
    resource_name: str,
    row_count: int,
    table_format: DataWarehouseTable.TableFormat,
    queryable_folder: str,
    table_schema_dict: dict[str, str] | None = None,
    set_as_schema_table: bool = False,
) -> None:
    """Synchronous version of register_cdc_companion_table for testing.

    Mirrors the inner _register() logic without the async/database_sync_to_async_pool wrapper.
    """
    if row_count == 0:
        return

    job = ExternalDataJob.objects.prefetch_related("pipeline").get(pk=run_id)
    normalized_resource_name = NamingConvention().normalize_identifier(resource_name)
    companion_table_name = build_table_name(job.pipeline, resource_name)
    new_url_pattern = job.url_pattern_by_schema(normalized_resource_name)

    table_params = {
        "name": companion_table_name,
        "format": table_format,
        "url_pattern": new_url_pattern,
        "team_id": team_id,
        "row_count": row_count,
        "queryable_folder": queryable_folder,
    }

    companion_table: DataWarehouseTable | None = DataWarehouseTable.objects.filter(
        team_id=team_id,
        name=companion_table_name,
        external_data_source_id=job.pipeline.id,
        deleted=False,
    ).first()

    if companion_table:
        companion_table.format = table_format
        companion_table.url_pattern = new_url_pattern
        companion_table.queryable_folder = queryable_folder
        companion_table.row_count = companion_table.get_count()
        companion_table.save()
    else:
        companion_table = DataWarehouseTable.objects.create(external_data_source_id=job.pipeline.id, **table_params)

    raw_db_columns = companion_table.get_columns()
    db_columns = {key: str(column.get("clickhouse", "")) for key, column in raw_db_columns.items()}
    existing_columns = companion_table.columns or {}
    columns = merge_columns(db_columns, table_schema_dict or {}, existing_columns)
    companion_table.columns = columns
    companion_table.save()

    if set_as_schema_table:
        ExternalDataSchema.objects.filter(id=schema_id, team_id=team_id).update(table=companion_table)


class TestRegisterCDCCompanionTable(BaseTest):
    def _create_source_and_job(self) -> tuple[ExternalDataSource, ExternalDataJob, ExternalDataSchema]:
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=self.user,
            job_inputs={"stripe_secret_key": "sk_test_123"},
        )
        schema = ExternalDataSchema.objects.create(
            name="orders",
            team_id=self.team.pk,
            source=source,
        )
        job = ExternalDataJob.objects.create(
            team_id=self.team.pk,
            pipeline=source,
            schema=schema,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
        )
        return source, job, schema

    @patch.object(DataWarehouseTable, "get_columns", return_value={})
    @patch.object(DataWarehouseTable, "get_count", return_value=100)
    def test_creates_companion_table(self, _mock_count, _mock_cols):
        source, job, schema = self._create_source_and_job()

        _register_companion_sync(
            run_id=str(job.id),
            team_id=self.team.pk,
            schema_id=schema.id,
            resource_name="orders_cdc",
            row_count=100,
            table_format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            queryable_folder="s3://bucket/cdc_folder",
            table_schema_dict={"id": "Int64", "name": "String"},
        )

        companion = DataWarehouseTable.objects.filter(
            team_id=self.team.pk,
            external_data_source_id=source.pk,
            deleted=False,
        ).exclude(id__in=[schema.table_id] if schema.table_id else [])

        assert companion.count() == 1
        table = companion.first()
        assert table is not None
        assert table.name.endswith("orders_cdc")
        assert table.queryable_folder == "s3://bucket/cdc_folder"

    @patch.object(DataWarehouseTable, "get_columns", return_value={})
    @patch.object(DataWarehouseTable, "get_count", return_value=200)
    def test_updates_existing_companion_table(self, _mock_count, _mock_cols):
        source, job, schema = self._create_source_and_job()

        _register_companion_sync(
            run_id=str(job.id),
            team_id=self.team.pk,
            schema_id=schema.id,
            resource_name="orders_cdc",
            row_count=100,
            table_format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            queryable_folder="s3://bucket/cdc_folder_v1",
        )

        _register_companion_sync(
            run_id=str(job.id),
            team_id=self.team.pk,
            schema_id=schema.id,
            resource_name="orders_cdc",
            row_count=200,
            table_format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            queryable_folder="s3://bucket/cdc_folder_v2",
        )

        companions = DataWarehouseTable.objects.filter(
            team_id=self.team.pk,
            external_data_source_id=source.pk,
            deleted=False,
        ).exclude(id__in=[schema.table_id] if schema.table_id else [])

        assert companions.count() == 1
        table = companions.first()
        assert table is not None
        assert table.queryable_folder == "s3://bucket/cdc_folder_v2"

    @patch.object(DataWarehouseTable, "get_columns", return_value={})
    @patch.object(DataWarehouseTable, "get_count", return_value=50)
    def test_set_as_schema_table_links_companion_to_schema(self, _mock_count, _mock_cols):
        source, job, schema = self._create_source_and_job()
        assert schema.table is None

        _register_companion_sync(
            run_id=str(job.id),
            team_id=self.team.pk,
            schema_id=schema.id,
            resource_name="orders_cdc",
            row_count=50,
            table_format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            queryable_folder="s3://bucket/cdc_folder",
            set_as_schema_table=True,
        )

        schema.refresh_from_db()
        table_name = getattr(schema.table, "name", None)
        assert table_name is not None
        assert table_name.endswith("orders_cdc")

    def test_skips_zero_rows(self):
        source, job, schema = self._create_source_and_job()

        _register_companion_sync(
            run_id=str(job.id),
            team_id=self.team.pk,
            schema_id=schema.id,
            resource_name="orders_cdc",
            row_count=0,
            table_format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            queryable_folder="s3://bucket/cdc_folder",
        )

        companions = DataWarehouseTable.objects.filter(
            team_id=self.team.pk,
            external_data_source_id=source.pk,
            deleted=False,
        )
        assert companions.count() == 0
