import concurrent.futures
import inspect
import json
import typing
from collections.abc import Sequence

import deltalake as deltalake
import deltalake.exceptions
import pyarrow as pa
import pyarrow.compute as pc
from conditional_cache import lru_cache
from django.conf import settings
from dlt.common.libs.deltalake import ensure_delta_compatible_arrow_schema
from dlt.common.normalizers.naming.snake_case import NamingConvention

from posthog.exceptions_capture import capture_exception
from posthog.settings.base_variables import TEST
from posthog.temporal.common.logger import FilteringBoundLogger
from posthog.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY
from posthog.temporal.data_imports.pipelines.pipeline.utils import normalize_column_name
from posthog.warehouse.models import ExternalDataJob
from posthog.warehouse.s3 import get_s3_client

MergeStatistics = dict[str, typing.Any]


class DeltaTableHelper:
    _resource_name: str
    _job: ExternalDataJob
    _logger: FilteringBoundLogger
    _is_first_sync: bool = False

    def __init__(self, resource_name: str, job: ExternalDataJob, logger: FilteringBoundLogger) -> None:
        self._resource_name = resource_name
        self._job = job
        self._logger = logger

    @property
    def logger(self):
        """Return a logger to use within this helper.

        We automatically bind the caller as "method".
        """
        try:
            caller = inspect.stack()[1].function
        except IndexError:
            return self._logger
        else:
            return self._logger.bind(method=caller)

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
                "AWS_S3_ALLOW_UNSAFE_RENAME": "false",
                "conditional_put": "etag",
            }

        return {
            "aws_access_key_id": settings.AIRBYTE_BUCKET_KEY,
            "aws_secret_access_key": settings.AIRBYTE_BUCKET_SECRET,
            "region_name": settings.AIRBYTE_BUCKET_REGION,
            "AWS_DEFAULT_REGION": settings.AIRBYTE_BUCKET_REGION,
            "AWS_S3_ALLOW_UNSAFE_RENAME": "false",
            "conditional_put": "etag",
        }

    def _get_delta_table_uri(self) -> str:
        normalized_resource_name = NamingConvention().normalize_identifier(self._resource_name)
        return f"{settings.BUCKET_URL}/{self._job.folder_path()}/{normalized_resource_name}"

    def _evolve_delta_schema(self, schema: pa.Schema) -> deltalake.DeltaTable:
        delta_table = self.get_delta_table()
        if delta_table is None:
            raise Exception("Deltalake table not found")

        delta_table_schema = delta_table.schema().to_pyarrow()

        new_fields = [
            deltalake.Field.from_pyarrow(field)
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
        self, data: pa.Table, is_incremental: bool, chunk_index: int, primary_keys: Sequence[str] | None
    ) -> deltalake.DeltaTable:
        logger = self.logger.bind(is_first_sync=str(self._is_first_sync))

        delta_table = self.get_delta_table()
        if delta_table:
            delta_table = self._evolve_delta_schema(data.schema)
            logger = logger.bind(table_uri=delta_table.table_uri)

        use_partitioning = False
        if PARTITION_KEY in data.column_names:
            use_partitioning = True
            logger.debug("Using partitioning on '%s'", PARTITION_KEY)

        if is_incremental and delta_table is not None and not self._is_first_sync:
            if not primary_keys or len(primary_keys) == 0:
                raise Exception("Primary key required for incremental syncs")

            logger.debug("Starting merge")

            # Normalize keys and check the keys actually exist in the dataset
            py_table_column_names = data.column_names
            normalized_primary_keys = [
                normalize_column_name(x) for x in primary_keys if normalize_column_name(x) in py_table_column_names
            ]
            predicate_ops = [f"source.{c} = target.{c}" for c in normalized_primary_keys]

            if use_partitioning:
                self.merge_partitioned_delta_table(delta_table, data, predicate_ops)

            else:
                _ = self.merge_delta_table(delta_table, data, predicate_ops)

        else:
            mode = "append"
            schema_mode = "merge"
            if chunk_index == 0 or delta_table is None:
                mode = "overwrite"
                schema_mode = "overwrite"

            logger = logger.bind(mode=mode)

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
                    engine="rust",
                    storage_options={
                        "conditional_put": "etag",
                    },
                )  # type: ignore
            except deltalake.exceptions.SchemaMismatchError as e:
                logger.exception("Attempting to overwrite schema due to SchemaMismatchError", exc_info=e)
                capture_exception(e)

                deltalake.write_deltalake(
                    table_or_uri=delta_table,
                    data=data,
                    partition_by=None,
                    mode=mode,
                    schema_mode="overwrite",
                    engine="rust",
                    storage_options={
                        "conditional_put": "etag",
                    },
                )  # type: ignore

        delta_table = self.get_delta_table()
        assert delta_table is not None

        return delta_table

    def merge_partitioned_delta_table(
        self,
        delta_table: deltalake.DeltaTable,
        data: pa.Table,
        predicate_ops: list[str],
        max_workers: int | None = None,
    ) -> None:
        """Execute merges of data partitions into partitioned delta table.

        This method orchestrates the execution of multiple merges (one per
        partition) concurrently. Assuming

        Arguments:
            delta_table: The delta table we are merging data into.
            data: The data we are merging into the delta table.
            predicate_ops: Merging predicate clauses.
            max_workers: Max number of threads to execute merges asynchronously.
                By default (i.e. passing `None`), we leave it up to
                `concurrent.futures.ThreadPoolExecutor` to decide how many
                workers to use.
        """
        logger = self.logger.bind(is_first_sync=str(self._is_first_sync), table_uri=delta_table.table_uri)

        predicate_ops = predicate_ops.copy()
        predicate_ops.append(f"source.{PARTITION_KEY} = target.{PARTITION_KEY}")

        # Group the table by the partition key and merge multiple times with streamed_exec=True for optimised merging
        unique_partitions = pc.unique(data[PARTITION_KEY])  # type: ignore
        logger.debug("Running %d optimised merges", len(unique_partitions))

        future_to_partition: dict[concurrent.futures.Future[MergeStatistics], str] = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            for partition in unique_partitions:
                partition_predicate_ops = predicate_ops.copy()
                partition_predicate_ops.append(f"target.{PARTITION_KEY} = '{partition}'")

                filtered_table = data.filter(pc.equal(data[PARTITION_KEY], partition))

                logger.debug(
                    "Submitting merge for partition '%s'",
                    partition,
                )

                future_to_partition[
                    executor.submit(
                        self.merge_delta_table, delta_table, filtered_table, partition_predicate_ops, streamed_exc=True
                    )
                ] = partition

            for future in concurrent.futures.as_completed(future_to_partition):
                partition = future_to_partition[future]

                try:
                    _ = future.result()
                except Exception as exc:
                    logger.exception("Failed to merge partition %s: %s", partition, exc)
                    raise
                else:
                    logger.debug("Successfully merged partition %s", partition)

    def merge_delta_table(
        self, delta_table: deltalake.DeltaTable, data: pa.Table, predicate_ops: list[str], streamed_exc: bool = False
    ) -> MergeStatistics:
        """Merge provided data into a delta table with provided predicate.

        Arguments:
            delta_table: The delta table we are merging data into.
            data: The data we are merging into the delta table.
            predicate_ops: Merging predicate clauses.
            streamed_exc: Passed along to merge call. Setting to `True` can
                enable a plan with less memory usage.
        """
        logger = self.logger.bind(is_first_sync=str(self._is_first_sync), table_uri=delta_table.table_uri)

        predicate = " AND ".join(predicate_ops)

        logger.debug("Merging with predicate '%s'", predicate)

        merge_stats = (
            delta_table.merge(
                source=data,
                source_alias="source",
                target_alias="target",
                predicate=predicate,
                streamed_exec=streamed_exc,
            )
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute()
        )

        logger.debug("Stats for successful merge: %s", json.dumps(merge_stats))

        return merge_stats

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
