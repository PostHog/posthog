from collections.abc import Sequence
import json
from conditional_cache import lru_cache
from typing import Any, Literal
import deltalake.exceptions
import pyarrow as pa
import pyarrow.compute as pc
from dlt.common.libs.deltalake import ensure_delta_compatible_arrow_schema
from dlt.common.normalizers.naming.snake_case import NamingConvention
import deltalake as deltalake
from django.conf import settings
from posthog.exceptions_capture import capture_exception
from posthog.settings.base_variables import TEST
from posthog.temporal.common.logger import FilteringBoundLogger
from posthog.temporal.data_imports.pipelines.pipeline.utils import (
    normalize_column_name,
)
from posthog.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY
from posthog.warehouse.models import ExternalDataJob
from posthog.warehouse.s3 import get_s3_client


class DeltaTableHelper:
    _resource_name: str
    _job: ExternalDataJob
    _logger: FilteringBoundLogger
    _is_first_sync: bool = False

    def __init__(self, resource_name: str, job: ExternalDataJob, logger: FilteringBoundLogger) -> None:
        self._resource_name = resource_name
        self._job = job
        self._logger = logger

    def _get_credentials(self):
        if not settings.AIRBYTE_BUCKET_KEY or not settings.AIRBYTE_BUCKET_SECRET or not settings.AIRBYTE_BUCKET_REGION:
            raise KeyError(
                "Missing env vars for data warehouse. Required vars: AIRBYTE_BUCKET_KEY, AIRBYTE_BUCKET_SECRET, AIRBYTE_BUCKET_REGION"
            )

        if TEST:
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

    def _get_delta_table_uri(self) -> str:
        normalized_resource_name = NamingConvention().normalize_identifier(self._resource_name)
        return f"{settings.BUCKET_URL}/{self._job.folder_path()}/{normalized_resource_name}"

    def _evolve_delta_schema(self, schema: pa.Schema) -> deltalake.DeltaTable:
        delta_table = self.get_delta_table()
        if delta_table is None:
            raise Exception("Deltalake table not found")

        delta_table_schema = delta_table.schema().to_arrow()

        new_fields = [
            deltalake.Field.from_arrow(field)
            for field in ensure_delta_compatible_arrow_schema(schema)
            if field.name not in delta_table_schema.names
        ]
        if new_fields:
            delta_table.alter.add_columns(new_fields)

        return delta_table

    @lru_cache(maxsize=1, condition=lambda result: result is not None)
    def get_delta_table(self) -> deltalake.DeltaTable | None:
        delta_uri = self._get_delta_table_uri()
        storage_options = self._get_credentials()

        if deltalake.DeltaTable.is_deltatable(table_uri=delta_uri, storage_options=storage_options):
            try:
                return deltalake.DeltaTable(table_uri=delta_uri, storage_options=storage_options)
            except Exception as e:
                # Temp fix for bugged tables
                capture_exception(e)
                if "parse decimal overflow" in "".join(e.args):
                    s3 = get_s3_client()
                    s3.delete(delta_uri, recursive=True)

        self._is_first_sync = True

        return None

    def reset_table(self):
        delta_uri = self._get_delta_table_uri()

        s3 = get_s3_client()
        try:
            s3.delete(delta_uri, recursive=True)
        except FileNotFoundError:
            pass

        self.get_delta_table.cache_clear()

        self._logger.debug("reset_table: _is_first_sync=True")
        self._is_first_sync = True

    def write_to_deltalake(
        self,
        data: pa.Table,
        write_type: Literal["incremental", "full_refresh", "append"],
        chunk_index: int,
        primary_keys: Sequence[Any] | None,
    ) -> deltalake.DeltaTable:
        delta_table = self.get_delta_table()

        if delta_table:
            delta_table = self._evolve_delta_schema(data.schema)

        self._logger.debug(f"write_to_deltalake: _is_first_sync = {self._is_first_sync}")

        use_partitioning = False
        if PARTITION_KEY in data.column_names:
            use_partitioning = True
            self._logger.debug(f"Using partitioning on {PARTITION_KEY}")

        if write_type == "incremental" and delta_table is not None and not self._is_first_sync:
            if not primary_keys or len(primary_keys) == 0:
                raise Exception("Primary key required for incremental syncs")

            self._logger.debug(f"write_to_deltalake: merging...")

            # Normalize keys and check the keys actually exist in the dataset
            py_table_column_names = data.column_names
            normalized_primary_keys = [
                normalize_column_name(x) for x in primary_keys if normalize_column_name(x) in py_table_column_names
            ]

            predicate_ops = [f"source.{c} = target.{c}" for c in normalized_primary_keys]
            if use_partitioning:
                predicate_ops.append(f"source.{PARTITION_KEY} = target.{PARTITION_KEY}")

                # Group the table by the partition key and merge multiple times with streamed_exec=True for optimised merging
                unique_partitions = pc.unique(data[PARTITION_KEY])  # type: ignore

                self._logger.debug(f"Running {len(unique_partitions)} optimised merges")

                for partition in unique_partitions:
                    partition_predicate_ops = predicate_ops.copy()
                    partition_predicate_ops.append(f"target.{PARTITION_KEY} = '{partition}'")
                    predicate = " AND ".join(partition_predicate_ops)

                    filtered_table = data.filter(pc.equal(data[PARTITION_KEY], partition))

                    self._logger.debug(f"Merging partition={partition} with predicate={predicate}")

                    merge_stats = (
                        delta_table.merge(
                            source=filtered_table,
                            source_alias="source",
                            target_alias="target",
                            predicate=predicate,
                            streamed_exec=True,
                        )
                        .when_matched_update_all()
                        .when_not_matched_insert_all()
                        .execute()
                    )

                    self._logger.debug(f"Delta Merge Stats: {json.dumps(merge_stats)}")
            else:
                merge_stats = (
                    delta_table.merge(
                        source=data,
                        source_alias="source",
                        target_alias="target",
                        predicate=" AND ".join(predicate_ops),
                        streamed_exec=False,
                    )
                    .when_matched_update_all()
                    .when_not_matched_insert_all()
                    .execute()
                )
                self._logger.debug(f"Delta Merge Stats: {json.dumps(merge_stats)}")
        elif (
            write_type == "full_refresh"
            or (write_type == "incremental" and delta_table is None)
            or (write_type == "incremental" and self._is_first_sync)
        ):
            mode: Literal["error", "append", "overwrite", "ignore"] = "append"
            schema_mode: Literal["merge", "overwrite"] | None = "merge"
            if chunk_index == 0 or delta_table is None:
                mode = "overwrite"
                schema_mode = "overwrite"

            self._logger.debug(f"write_to_deltalake: mode = {mode}")

            if delta_table is None:
                storage_options = self._get_credentials()
                delta_table = deltalake.DeltaTable.create(
                    table_uri=self._get_delta_table_uri(),
                    schema=data.schema,
                    storage_options=storage_options,
                    partition_by=PARTITION_KEY if use_partitioning else None,
                )

            try:
                deltalake.write_deltalake(
                    table_or_uri=delta_table,
                    data=data,
                    partition_by=PARTITION_KEY if use_partitioning else None,
                    mode=mode,
                    schema_mode=schema_mode,
                )
            except deltalake.exceptions.SchemaMismatchError as e:
                self._logger.debug("SchemaMismatchError: attempting to overwrite schema instead", exc_info=e)
                capture_exception(e)

                deltalake.write_deltalake(
                    table_or_uri=delta_table,
                    data=data,
                    partition_by=None,
                    mode=mode,
                    schema_mode="overwrite",
                )
        elif write_type == "append":
            if delta_table is None:
                storage_options = self._get_credentials()
                delta_table = deltalake.DeltaTable.create(
                    table_uri=self._get_delta_table_uri(),
                    schema=data.schema,
                    storage_options=storage_options,
                    partition_by=PARTITION_KEY if use_partitioning else None,
                )

            self._logger.debug(f"write_to_deltalake: write_type = append")

            deltalake.write_deltalake(
                table_or_uri=delta_table,
                data=data,
                partition_by=PARTITION_KEY if use_partitioning else None,
                mode="append",
                schema_mode="merge",
            )

        delta_table = self.get_delta_table()
        assert delta_table is not None

        return delta_table

    def compact_table(self) -> None:
        table = self.get_delta_table()
        if table is None:
            raise Exception("Deltatable not found")

        self._logger.debug("Compacting table...")
        compact_stats = table.optimize.compact()
        self._logger.debug(json.dumps(compact_stats))

        self._logger.debug("Vacuuming table...")
        vacuum_stats = table.vacuum(retention_hours=24, enforce_retention_duration=False, dry_run=False)
        self._logger.debug(json.dumps(vacuum_stats))

        self._logger.debug("Compacting and vacuuming complete")
