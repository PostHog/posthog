import math
from datetime import UTC, datetime

from django.conf import settings

import pyarrow as pa
import deltalake as deltalake
import pyarrow.compute as pc
from conditional_cache import lru_cache

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY
from posthog.temporal.data_imports.pipelines.pipeline.hogql_schema import HogQLSchema
from posthog.temporal.data_imports.pipelines.pipeline.utils import DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES
from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from posthog.warehouse.models.snapshot_config import DataWarehouseSnapshotConfig
from posthog.warehouse.s3 import ensure_bucket_exists
from posthog.warehouse.types import PartitionSettings


class DeltaSnapshot:
    VALID_UNTIL_COLUMN: str = "valid_until"

    def __init__(self, saved_query: DataWarehouseSavedQuery):
        self.saved_query = saved_query
        self.schema = HogQLSchema()

    @property
    def merge_key(self) -> str | None:
        return self.saved_query.datawarehousesnapshotconfig.config.get("merge_key", None)

    @property
    def columns(self) -> list[str]:
        return self.saved_query.datawarehousesnapshotconfig.config.get("fields", [])

    def _get_delta_table_uri(self) -> str:
        return f"{settings.BUCKET_URL}/team_{self.saved_query.team.pk}_snapshot_{self.saved_query.id.hex}/snapshots/{self.saved_query.normalized_name}"

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

    def snapshot(self, data: pa.RecordBatch):
        delta_table = self.get_delta_table()
        self.schema.add_pyarrow_record_batch(data)

        if PARTITION_KEY in data.column_names:
            use_partitioning = True

        if delta_table is None:
            delta_table = deltalake.DeltaTable.create(
                table_uri=self._get_delta_table_uri(),
                schema=data.schema,
                storage_options=self._get_credentials(),
                partition_by=PARTITION_KEY if use_partitioning else None,
            )

        if use_partitioning:
            predicate_ops = ["source.merge_key = target.merge_key", f"source.{PARTITION_KEY} = target.{PARTITION_KEY}"]
            unique_partitions = pc.unique(data[PARTITION_KEY])
            for partition in unique_partitions:
                predicate_ops.append(f"target.{PARTITION_KEY} = '{partition}'")
                predicate = " AND ".join(predicate_ops)
                filtered_table = data.filter(pc.equal(data[PARTITION_KEY], partition))
                self._merge_table(delta_table, filtered_table, predicate)
            self._merge_table(delta_table, data, predicate)
        else:
            self._merge_table(delta_table, data, "source.merge_key = target.merge_key")

    def _merge_table(self, delta_table: deltalake.DeltaTable, data: pa.RecordBatch, predicate: str):
        now_micros = int(datetime.now(UTC).timestamp() * 1_000_000)
        delta_table.merge(
            source=data,
            source_alias="source",
            target_alias="target",
            predicate=predicate,
            streamed_exec=True,
        ).when_matched_update(
            updates={
                # indicates update
                "valid_until": "source.snapshot_ts",
            },
            predicate="source.row_hash != target.row_hash AND target.valid_until IS NULL",
        ).when_not_matched_by_source_update(
            updates={
                # indicates deletion
                "valid_until": f"to_timestamp_micros({now_micros})",
            },
            predicate="target.valid_until IS NULL",
            # insert brand new rows
        ).when_not_matched_insert_all().execute()

        # Insert the updated rows
        delta_table.merge(
            source=data,
            source_alias="source",
            target_alias="target",
            predicate=f"source.merge_key = target.merge_key AND target.valid_until IS NULL",
            streamed_exec=True,
        ).when_not_matched_insert_all().execute()


def calculate_partition_settings(saved_query: DataWarehouseSavedQuery) -> PartitionSettings | None:
    view_table = saved_query.table

    total_rows = view_table.row_count
    total_size_mib = view_table.size_in_s3_mib

    if total_rows is None or total_size_mib is None:
        return None

    partition_size = DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES / (total_size_mib / total_rows)
    partition_count = math.floor(total_rows / partition_size)

    if partition_count == 0:
        return PartitionSettings(partition_count=1, partition_size=partition_size)

    return PartitionSettings(partition_count=partition_count, partition_size=partition_size)


def get_partition_settings(saved_query: DataWarehouseSavedQuery) -> PartitionSettings | None:
    try:
        config = saved_query.datawarehousesnapshotconfig.config
    except DataWarehouseSnapshotConfig.DoesNotExist:
        return None

    count = config.get("partition_count", None)
    size = config.get("partition_size", None)

    if count is None or size is None:
        return None

    return PartitionSettings(partition_count=count, partition_size=size)
