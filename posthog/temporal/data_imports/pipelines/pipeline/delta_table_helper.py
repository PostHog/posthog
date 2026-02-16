import json
import asyncio
from collections.abc import Sequence
from typing import Any, Literal

from django.conf import settings

import pyarrow as pa
import deltalake as deltalake
import pyarrow.compute as pc
import deltalake.exceptions
from dlt.common.libs.deltalake import ensure_delta_compatible_arrow_schema
from dlt.common.normalizers.naming.snake_case import NamingConvention
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY
from posthog.temporal.data_imports.pipelines.pipeline.utils import conditional_lru_cache_async, normalize_column_name

from products.data_warehouse.backend.models import ExternalDataJob
from products.data_warehouse.backend.s3 import aget_s3_client, ensure_bucket_exists


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
        if settings.USE_LOCAL_SETUP:
            if (
                not settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY
                or not settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET
                or not settings.DATAWAREHOUSE_LOCAL_BUCKET_REGION
            ):
                raise KeyError(
                    "Missing env vars for data warehouse. Required vars: DATAWAREHOUSE_LOCAL_ACCESS_KEY, DATAWAREHOUSE_LOCAL_ACCESS_SECRET, DATAWAREHOUSE_LOCAL_BUCKET_REGION"
                )

            ensure_bucket_exists(
                settings.BUCKET_URL,
                settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
                settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
                settings.OBJECT_STORAGE_ENDPOINT,
            )

            return {
                "aws_access_key_id": settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
                "aws_secret_access_key": settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
                "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
                "region_name": settings.DATAWAREHOUSE_LOCAL_BUCKET_REGION,
                "AWS_DEFAULT_REGION": settings.DATAWAREHOUSE_LOCAL_BUCKET_REGION,
                "AWS_ALLOW_HTTP": "true",
                "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
            }

        return {
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    async def _get_delta_table_uri(self) -> str:
        normalized_resource_name = NamingConvention().normalize_identifier(self._resource_name)
        folder_path = await database_sync_to_async_pool(self._job.folder_path)()
        return f"{settings.BUCKET_URL}/{folder_path}/{normalized_resource_name}"

    async def _evolve_delta_schema(self, schema: pa.Schema) -> deltalake.DeltaTable:
        delta_table = await self.get_delta_table()
        if delta_table is None:
            raise Exception("Deltalake table not found")

        delta_table_schema = delta_table.schema().to_pyarrow()

        new_fields = [
            deltalake.Field.from_pyarrow(field)
            for field in ensure_delta_compatible_arrow_schema(schema)
            if field.name not in delta_table_schema.names
        ]
        if new_fields:
            await asyncio.to_thread(delta_table.alter.add_columns, new_fields)

        return delta_table

    @conditional_lru_cache_async(maxsize=1, condition=lambda result: result is not None)
    async def get_delta_table(self) -> deltalake.DeltaTable | None:
        delta_uri = await self._get_delta_table_uri()
        storage_options = self._get_credentials()

        is_delta = await asyncio.to_thread(
            deltalake.DeltaTable.is_deltatable, table_uri=delta_uri, storage_options=storage_options
        )
        if is_delta:
            try:
                return await asyncio.to_thread(
                    deltalake.DeltaTable, table_uri=delta_uri, storage_options=storage_options
                )
            except Exception as e:
                # Temp fix for bugged tables
                capture_exception(e)
                if "parse decimal overflow" in "".join(e.args):
                    async with aget_s3_client() as s3:
                        await s3._rm(delta_uri, recursive=True)
                else:
                    raise

        self._is_first_sync = True

        return None

    async def reset_table(self):
        delta_uri = await self._get_delta_table_uri()

        async with aget_s3_client() as s3:
            try:
                await s3._rm(delta_uri, recursive=True)
            except FileNotFoundError:
                pass

        self.get_delta_table.cache_clear()

        await self._logger.adebug("reset_table: _is_first_sync=True")
        self._is_first_sync = True

    async def get_file_uris(self) -> list[str]:
        delta_table = await self.get_delta_table()
        if delta_table is None:
            return []

        return await asyncio.to_thread(delta_table.file_uris)

    async def write_to_deltalake(
        self,
        data: pa.Table,
        write_type: Literal["incremental", "full_refresh", "append"],
        should_overwrite_table: bool,
        primary_keys: Sequence[Any] | None,
    ) -> deltalake.DeltaTable:
        delta_table = await self.get_delta_table()

        if delta_table:
            delta_table = await self._evolve_delta_schema(data.schema)

        await self._logger.adebug(
            f"write_to_deltalake: _is_first_sync = {self._is_first_sync}. should_overwrite_table = {should_overwrite_table}"
        )

        use_partitioning = False
        if PARTITION_KEY in data.column_names:
            use_partitioning = True
            await self._logger.adebug(f"Using partitioning on {PARTITION_KEY}")

        if write_type == "incremental" and delta_table is not None and not self._is_first_sync:
            if not primary_keys or len(primary_keys) == 0:
                raise Exception("Primary key required for incremental syncs")

            await self._logger.adebug(f"write_to_deltalake: merging...")

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

                await self._logger.adebug(f"Running {len(unique_partitions)} optimised merges")

                for partition in unique_partitions:
                    partition_predicate_ops = predicate_ops.copy()
                    partition_predicate_ops.append(f"target.{PARTITION_KEY} = '{partition}'")
                    predicate = " AND ".join(partition_predicate_ops)

                    filtered_table = data.filter(pc.equal(data[PARTITION_KEY], partition))

                    await self._logger.adebug(f"Merging partition={partition} with predicate={predicate}")

                    def _do_merge(filtered_table: pa.Table, predicate: str):
                        return (
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

                    merge_stats = await asyncio.to_thread(_do_merge, filtered_table, predicate)

                    await self._logger.adebug(f"Delta Merge Stats: {json.dumps(merge_stats)}")
            else:

                def _do_merge_unpartitioned(data: pa.Table, predicate_ops: list[str]):
                    return (
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

                merge_stats = await asyncio.to_thread(_do_merge_unpartitioned, data, predicate_ops)
                await self._logger.adebug(f"Delta Merge Stats: {json.dumps(merge_stats)}")
        elif (
            write_type == "full_refresh"
            or (write_type == "incremental" and delta_table is None)
            or (write_type == "incremental" and self._is_first_sync)
        ):
            mode: Literal["error", "append", "overwrite", "ignore"] = "append"
            schema_mode: Literal["merge", "overwrite"] | None = "merge"
            if should_overwrite_table or delta_table is None:
                mode = "overwrite"
                schema_mode = "overwrite"

            await self._logger.adebug(f"write_to_deltalake: mode = {mode}")

            if delta_table is None:
                storage_options = self._get_credentials()
                delta_uri = await self._get_delta_table_uri()
                delta_table = await asyncio.to_thread(
                    deltalake.DeltaTable.create,
                    table_uri=delta_uri,
                    schema=data.schema,
                    storage_options=storage_options,
                    partition_by=PARTITION_KEY if use_partitioning else None,
                )

            try:
                await asyncio.to_thread(
                    deltalake.write_deltalake,
                    table_or_uri=delta_table,
                    data=data,
                    partition_by=PARTITION_KEY if use_partitioning else None,
                    mode=mode,
                    schema_mode=schema_mode,
                    engine="rust",
                )
            except deltalake.exceptions.SchemaMismatchError as e:
                await self._logger.adebug("SchemaMismatchError: attempting to overwrite schema instead", exc_info=e)
                capture_exception(e)

                await asyncio.to_thread(
                    deltalake.write_deltalake,
                    table_or_uri=delta_table,
                    data=data,
                    partition_by=None,
                    mode=mode,
                    schema_mode="overwrite",
                    engine="rust",
                )
        elif write_type == "append":
            if delta_table is None:
                storage_options = self._get_credentials()
                delta_uri = await self._get_delta_table_uri()
                delta_table = await asyncio.to_thread(
                    deltalake.DeltaTable.create,
                    table_uri=delta_uri,
                    schema=data.schema,
                    storage_options=storage_options,
                    partition_by=PARTITION_KEY if use_partitioning else None,
                )

            await self._logger.adebug(f"write_to_deltalake: write_type = append")

            await asyncio.to_thread(
                deltalake.write_deltalake,
                table_or_uri=delta_table,
                data=data,
                partition_by=PARTITION_KEY if use_partitioning else None,
                mode="append",
                schema_mode="merge",
                engine="rust",
            )

        delta_table = await self.get_delta_table()
        assert delta_table is not None

        return delta_table

    async def compact_table(self) -> None:
        table = await self.get_delta_table()
        if table is None:
            raise Exception("Deltatable not found")

        await self._logger.adebug("Compacting table...")
        compact_stats = await asyncio.to_thread(table.optimize.compact)
        await self._logger.adebug(json.dumps(compact_stats))

        await self._logger.adebug("Vacuuming table...")
        vacuum_stats = await asyncio.to_thread(
            table.vacuum, retention_hours=24, enforce_retention_duration=False, dry_run=False
        )
        await self._logger.adebug(json.dumps(vacuum_stats))

        await self._logger.adebug("Compacting and vacuuming complete")
