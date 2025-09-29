import math
from datetime import datetime

from django.conf import settings

import pyarrow as pa
import deltalake as deltalake
import pyarrow.compute as pc
from conditional_cache import lru_cache
from dlt.common.libs.deltalake import ensure_delta_compatible_arrow_schema

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY
from posthog.temporal.data_imports.pipelines.pipeline.hogql_schema import HogQLSchema
from posthog.temporal.data_imports.pipelines.pipeline.utils import DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES
from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from posthog.warehouse.models.snapshot_config import DataWarehouseSnapshotConfig
from posthog.warehouse.s3 import ensure_bucket_exists
from posthog.warehouse.types import PartitionSettings


def make_schema_nullable(schema: pa.Schema) -> pa.Schema:
    """Convert all fields in a PyArrow schema to nullable."""
    nullable_fields = []
    for field in schema:
        # Create a new field with the same name and type, but nullable=True
        nullable_field = field.with_nullable(True)
        nullable_fields.append(nullable_field)
    return pa.schema(nullable_fields)


class DeltaSnapshot:
    VALID_UNTIL_COLUMN: str = "_ph_valid_until"

    def __init__(self, saved_query: DataWarehouseSavedQuery):
        self.saved_query = saved_query
        self.schema = HogQLSchema()

    @property
    def merge_key(self) -> str | None:
        return self.saved_query.datawarehousesnapshotconfig.merge_key

    @property
    def columns(self) -> list[str]:
        return self.saved_query.datawarehousesnapshotconfig.fields

    def _get_delta_table_uri(self) -> str:
        return f"{settings.BUCKET_URL}/{self.saved_query.snapshot_folder_path}/{self.saved_query.normalized_name}"

    @property
    def backup_delta_table_uri(self) -> str:
        return self._get_delta_table_uri() + "__backup"

    def _get_credentials(self):
        if not settings.AIRBYTE_BUCKET_KEY or not settings.AIRBYTE_BUCKET_SECRET or not settings.AIRBYTE_BUCKET_REGION:
            raise KeyError(
                "Missing env vars for data warehouse. Required vars: AIRBYTE_BUCKET_KEY, AIRBYTE_BUCKET_SECRET, AIRBYTE_BUCKET_REGION"
            )

        if settings.USE_LOCAL_SETUP:
            ensure_bucket_exists(
                settings.BUCKET_URL,
                settings.AIRBYTE_BUCKET_KEY,
                settings.AIRBYTE_BUCKET_SECRET,
                settings.OBJECT_STORAGE_ENDPOINT,
            )

            return {
                "aws_access_key_id": settings.AIRBYTE_BUCKET_KEY,
                "aws_secret_access_key": settings.AIRBYTE_BUCKET_SECRET,
                "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
                "region_name": settings.AIRBYTE_BUCKET_REGION,
                "AWS_DEFAULT_REGION": settings.AIRBYTE_BUCKET_REGION,
                "AWS_ALLOW_HTTP": "true",
                "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
            }

        return {
            "aws_access_key_id": settings.AIRBYTE_BUCKET_KEY,
            "aws_secret_access_key": settings.AIRBYTE_BUCKET_SECRET,
            "region_name": settings.AIRBYTE_BUCKET_REGION,
            "AWS_DEFAULT_REGION": settings.AIRBYTE_BUCKET_REGION,
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    @lru_cache(maxsize=1, condition=lambda result: result is not None)
    def get_delta_table(self) -> deltalake.DeltaTable | None:
        delta_uri = self._get_delta_table_uri()
        storage_options = self._get_credentials()

        if deltalake.DeltaTable.is_deltatable(table_uri=delta_uri, storage_options=storage_options):
            try:
                return deltalake.DeltaTable(table_uri=delta_uri, storage_options=storage_options)
            except Exception as e:
                capture_exception(e)

        return None

    def _evolve_delta_schema(self, schema: pa.Schema) -> deltalake.DeltaTable:
        delta_table = self.get_delta_table()
        if delta_table is None:
            raise Exception("Deltalake table not found")

        delta_table_schema = delta_table.schema().to_pyarrow()

        new_fields = [
            deltalake.Field.from_pyarrow(field.with_nullable(True))
            for field in ensure_delta_compatible_arrow_schema(schema)
            if field.name not in delta_table_schema.names
        ]
        if new_fields:
            delta_table.alter.add_columns(new_fields)

        return delta_table

    def snapshot(self, data: pa.RecordBatch, snapshot_now: datetime):
        delta_table = self.get_delta_table()
        self.schema.add_pyarrow_record_batch(data)

        partition_exists = PARTITION_KEY in data.column_names

        if not partition_exists:
            raise Exception("Partition key not found in data. This is required for snapshots.")

        if delta_table is None:
            delta_table = deltalake.DeltaTable.create(
                table_uri=self._get_delta_table_uri(),
                schema=make_schema_nullable(data.schema),
                storage_options=self._get_credentials(),
                partition_by=PARTITION_KEY,
            )
        else:
            delta_table = self._evolve_delta_schema(data.schema)

        predicate_ops = [
            "source._ph_merge_key = target._ph_merge_key",
        ]
        unique_partitions = pc.unique(data[PARTITION_KEY])
        for partition in unique_partitions:
            predicate_ops.append(f"target.{PARTITION_KEY} = '{partition}'")
            predicate = " AND ".join(predicate_ops)
            filtered_table = data.filter(pc.equal(data[PARTITION_KEY], partition))
            self._merge_table(delta_table, filtered_table, predicate, snapshot_now)

    def _merge_table(
        self, delta_table: deltalake.DeltaTable, data: pa.RecordBatch, predicate: str, snapshot_now: datetime
    ):
        now_micros = int(snapshot_now.timestamp() * 1_000_000)

        delta_table.merge(
            source=data,
            source_alias="source",
            target_alias="target",
            predicate=predicate,
            streamed_exec=True,
        ).when_matched_update(
            updates={
                # indicates update
                "_ph_valid_until": "source._ph_snapshot_ts",
            },
            predicate="source._ph_row_hash != target._ph_row_hash AND target._ph_valid_until IS NULL",
        ).when_not_matched_by_source_update(
            updates={
                # indicates deletion
                "_ph_valid_until": f"to_timestamp_micros({now_micros})",
            },
            predicate="target._ph_valid_until IS NULL",
            # insert brand new rows
        ).when_not_matched_insert_all().execute()

        # Insert the updated rows
        delta_table.merge(
            source=data,
            source_alias="source",
            target_alias="target",
            predicate=f"{predicate} AND target._ph_valid_until IS NULL",
            streamed_exec=True,
        ).when_not_matched_insert_all().execute()


def calculate_partition_settings(saved_query: DataWarehouseSavedQuery) -> PartitionSettings | None:
    view_table = saved_query.table

    if view_table is None:
        return None

    total_rows = view_table.row_count
    total_size_mib = view_table.size_in_s3_mib

    if total_rows is None or total_size_mib is None or total_size_mib == 0:
        return None

    # Calculate approximate rows per partition based on target size; cast to int for PartitionSettings
    partition_size_float = DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES / (total_size_mib / total_rows)
    partition_size = int(partition_size_float)
    partition_count = math.floor(total_rows / max(1, partition_size))

    if partition_count <= 0:
        return PartitionSettings(partition_count=1, partition_size=int(max(1, partition_size)))

    return PartitionSettings(partition_count=partition_count, partition_size=partition_size)


def get_partition_settings(saved_query: DataWarehouseSavedQuery) -> PartitionSettings | None:
    try:
        config = saved_query.datawarehousesnapshotconfig
    except DataWarehouseSnapshotConfig.DoesNotExist:
        return None

    count = config.partition_count

    if count is None:
        return None

    return PartitionSettings(partition_count=count)
