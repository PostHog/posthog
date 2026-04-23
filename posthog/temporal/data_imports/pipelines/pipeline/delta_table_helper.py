import json
import asyncio
from collections.abc import Callable, Sequence
from typing import Any, Literal

from django.conf import settings

import numpy as np
import pyarrow as pa
import deltalake as deltalake
import pyarrow.compute as pc
import deltalake.exceptions
from dlt.common.libs.deltalake import ensure_delta_compatible_arrow_schema
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.data_imports.naming_convention import NamingConvention
from posthog.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY
from posthog.temporal.data_imports.pipelines.pipeline.utils import (
    conditional_lru_cache_async,
    normalize_column_name,
    pyarrow_schema_from_arrow_exportable,
)

from products.data_warehouse.backend.models import ExternalDataJob
from products.data_warehouse.backend.s3 import aget_s3_client, ensure_bucket_exists


def _write_deltalake(
    table_or_uri: str | deltalake.DeltaTable,
    table_data: pa.Table,
    partition_by: str | None,
    mode: Literal["error", "append", "overwrite", "ignore"],
    schema_mode: Literal["merge", "overwrite"] | None,
    commit_properties: deltalake.CommitProperties | None = None,
) -> None:
    deltalake.write_deltalake(
        table_or_uri=table_or_uri,
        data=table_data,
        partition_by=partition_by,
        mode=mode,
        schema_mode=schema_mode,
        commit_properties=commit_properties,
    )


def _first_per_pk_table(pa_table: pa.Table, pk_columns: list[str]) -> pa.Table:
    """Return a table containing only the first row per PK tuple (in original row order).

    Used when closing existing "current" rows during SCD2 append: we pass a
    deduplicated table to the merge so that only one source row matches each
    target row, avoiding ambiguous multi-match merge semantics.
    """
    if not pk_columns or pa_table.num_rows == 0:
        return pa_table

    # Strategy: tag every row with its position, group by PK, and for each PK
    # take the smallest position. That position is the first time we saw that PK.
    # Sorting those positions at the end restores the original row order.
    #
    # We use numpy for the final sort because pyarrow's type stubs for
    # `pc.sort_indices` / `Array.take` are currently broken — numpy's stubs work.
    idx_col_name = "__ph_cdc_row_idx"

    # 1. Add a row-position column: [0, 1, 2, ..., n-1]
    indexed = pa_table.append_column(idx_col_name, pa.array(range(pa_table.num_rows), type=pa.int64()))

    # 2. Group by PK, keeping only the smallest position per PK (= first occurrence)
    grouped = indexed.group_by(pk_columns).aggregate([(idx_col_name, "min")])

    # 3. Sort those positions ascending so the output mirrors the input row order
    first_indices = np.sort(grouped.column(f"{idx_col_name}_min").to_numpy())

    # 4. Materialize the rows at those positions from the original table
    return pa_table.take(first_indices)


class DeltaTableHelper:
    _resource_name: str
    _job: ExternalDataJob
    _logger: FilteringBoundLogger
    _is_first_sync: bool

    def __init__(
        self, resource_name: str, job: ExternalDataJob, logger: FilteringBoundLogger, is_first_sync: bool = False
    ) -> None:
        self._resource_name = resource_name
        self._job = job
        self._logger = logger
        self._is_first_sync = is_first_sync

    @property
    def is_first_sync(self) -> bool:
        return self._is_first_sync

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
        normalized_resource_name = NamingConvention.normalize_identifier(self._resource_name)
        folder_path = await database_sync_to_async_pool(self._job.folder_path)()
        return f"{settings.BUCKET_URL}/{folder_path}/{normalized_resource_name}"

    async def _evolve_delta_schema(self, schema: pa.Schema) -> deltalake.DeltaTable:
        delta_table = await self.get_delta_table()
        if delta_table is None:
            raise Exception("Deltalake table not found")

        delta_table_schema = pyarrow_schema_from_arrow_exportable(delta_table.schema())

        new_fields = [
            deltalake.Field.from_arrow(field)
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
        progress_callback: Callable[[], None] | None = None,
        commit_metadata: dict[str, str] | None = None,
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

        commit_properties: deltalake.CommitProperties | None = (
            deltalake.CommitProperties(custom_metadata=commit_metadata) if commit_metadata else None
        )

        if write_type == "incremental" and delta_table is not None and not self._is_first_sync:
            if not primary_keys or len(primary_keys) == 0:
                raise Exception("Primary key required for incremental syncs")

            existing_delta_table = delta_table

            await self._logger.adebug(f"write_to_deltalake: merging...")

            # Normalize keys and check the keys actually exist in the dataset
            py_table_column_names = data.column_names
            normalized_primary_keys: list[str] = []
            for x in primary_keys:
                n = normalize_column_name(x)
                if n in py_table_column_names:
                    normalized_primary_keys.append(n)

            predicate_ops = [f"source.{c} = target.{c}" for c in normalized_primary_keys]
            if use_partitioning:
                predicate_ops.append(f"source.{PARTITION_KEY} = target.{PARTITION_KEY}")

                # Group the table by the partition key and merge multiple times with streamed_exec=True for optimised merging
                unique_partitions = list(pc.unique(data[PARTITION_KEY]))  # type: ignore

                await self._logger.adebug(f"Running {len(unique_partitions)} optimised merges")

                # Only tag the FINAL partition merge with `commit_properties`. Intermediate
                # merges must remain untagged so a crash mid-loop doesn't leave behind a
                # tagged commit that would cause `has_batch_been_committed` to skip the
                # remaining partitions on Kafka redelivery (which would lose data).
                last_partition_index = len(unique_partitions) - 1
                for i, partition in enumerate(unique_partitions):
                    partition_predicate_ops = predicate_ops.copy()
                    partition_predicate_ops.append(f"target.{PARTITION_KEY} = '{partition}'")
                    predicate = " AND ".join(partition_predicate_ops)

                    filtered_table = data.filter(pc.equal(data[PARTITION_KEY], partition))

                    await self._logger.adebug(f"Merging partition={partition} with predicate={predicate}")

                    merge_commit_properties = commit_properties if i == last_partition_index else None

                    def _do_merge(
                        filtered_table: pa.Table,
                        predicate: str,
                        merge_commit_properties: deltalake.CommitProperties | None,
                    ):
                        return (
                            existing_delta_table.merge(
                                source=filtered_table,
                                source_alias="source",
                                target_alias="target",
                                predicate=predicate,
                                streamed_exec=True,
                                commit_properties=merge_commit_properties,
                            )
                            .when_matched_update_all()
                            .when_not_matched_insert_all()
                            .execute()
                        )

                    merge_stats = await asyncio.to_thread(_do_merge, filtered_table, predicate, merge_commit_properties)

                    await self._logger.adebug(f"Delta Merge Stats: {json.dumps(merge_stats)}")

                    if progress_callback:
                        progress_callback()
            else:
                # Single merge call → safe to tag directly; this is the terminal commit.
                def _do_merge_unpartitioned(data: pa.Table, predicate_ops: list[str]):
                    return (
                        existing_delta_table.merge(
                            source=data,
                            source_alias="source",
                            target_alias="target",
                            predicate=" AND ".join(predicate_ops),
                            streamed_exec=False,
                            commit_properties=commit_properties,
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
                    _write_deltalake,
                    delta_table,
                    data,
                    partition_by=PARTITION_KEY if use_partitioning else None,
                    mode=mode,
                    schema_mode=schema_mode,
                    commit_properties=commit_properties,
                )
            except deltalake.exceptions.SchemaMismatchError as e:
                await self._logger.adebug("SchemaMismatchError: attempting to overwrite schema instead", exc_info=e)
                capture_exception(e)

                await asyncio.to_thread(
                    _write_deltalake,
                    delta_table,
                    data,
                    partition_by=None,
                    mode=mode,
                    schema_mode="overwrite",
                    commit_properties=commit_properties,
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
                _write_deltalake,
                delta_table,
                data,
                partition_by=PARTITION_KEY if use_partitioning else None,
                mode="append",
                schema_mode="merge",
                commit_properties=commit_properties,
            )

        delta_table = await self.get_delta_table()
        assert delta_table is not None

        return delta_table

    async def write_scd2_to_deltalake(
        self,
        data: pa.Table,
        primary_keys: Sequence[Any],
        commit_metadata: dict[str, str] | None = None,
    ) -> deltalake.DeltaTable:
        """Write CDC SCD Type 2 data: close existing current rows, then append new rows.

        For each PK that appears in `data`:
        1. Find the existing row in the target with matching PK and valid_to IS NULL
           (the current row) and update its valid_to to the earliest valid_from of the
           new events for that PK.
        2. Append all rows from `data` as new history entries.

        `data` is expected to already have valid_from / valid_to columns as produced
        by batcher.build_scd2_table().
        """
        delta_table = await self.get_delta_table()

        if delta_table:
            delta_table = await self._evolve_delta_schema(data.schema)

        commit_properties: deltalake.CommitProperties | None = (
            deltalake.CommitProperties(custom_metadata=commit_metadata) if commit_metadata else None
        )

        # Step 1: Close existing current rows for PKs in this batch
        if delta_table is not None and primary_keys and "valid_from" in data.column_names:
            existing_delta_table = delta_table
            py_column_names = data.column_names
            normalized_pks: list[str] = []
            for x in primary_keys:
                n = normalize_column_name(x)
                if n in py_column_names:
                    normalized_pks.append(n)

            if normalized_pks:
                # Use only the first row per PK to avoid ambiguous multi-match merge
                first_per_pk = _first_per_pk_table(data, normalized_pks)

                predicate_parts = [f"source.{col} = target.{col}" for col in normalized_pks]
                predicate_parts.append("target.valid_to IS NULL")
                predicate = " AND ".join(predicate_parts)

                # NOTE: do NOT tag this intermediate merge with `commit_properties`. SCD2 is a
                # two-step write (close-existing then append-new); if we tagged step 1 with the
                # same (run_uuid, batch_index) and the process crashed before step 2, Kafka
                # redelivery would see the tagged commit, treat the batch as already done, and
                # silently skip the append → data loss. Tag only the terminal commit (step 2).
                def _do_scd2_close(first_per_pk: pa.Table, predicate: str) -> dict:
                    return (
                        existing_delta_table.merge(
                            source=first_per_pk,
                            source_alias="source",
                            target_alias="target",
                            predicate=predicate,
                            streamed_exec=False,
                        )
                        .when_matched_update(updates={"valid_to": "source.valid_from"})
                        .execute()
                    )

                close_stats = await asyncio.to_thread(_do_scd2_close, first_per_pk, predicate)
                await self._logger.adebug(f"SCD2 close stats: {json.dumps(close_stats)}")

        # Step 2: Append all new rows
        if delta_table is None:
            storage_options = self._get_credentials()
            delta_uri = await self._get_delta_table_uri()
            delta_table = await asyncio.to_thread(
                deltalake.DeltaTable.create,
                table_uri=delta_uri,
                schema=data.schema,
                storage_options=storage_options,
            )

        await asyncio.to_thread(
            deltalake.write_deltalake,
            table_or_uri=delta_table,
            data=data,
            mode="append",
            schema_mode="merge",
            commit_properties=commit_properties,
        )

        delta_table = await self.get_delta_table()
        assert delta_table is not None
        return delta_table

    async def has_commit_with_metadata(self, match: dict[str, str], *, scan_limit: int = 50) -> bool:
        """Check whether any recent delta commit has custom metadata matching all entries in `match`.

        Used to detect that a given (run_uuid, batch_index) has already been written
        even when a faster external dedup cache (e.g. Redis) is missing the marker —
        the canonical case is a writer crash between a successful `write_to_deltalake`
        and the subsequent cache update.

        delta-rs `history()` returns commits where `CommitProperties.custom_metadata`
        entries are flattened directly into the commit dict alongside `operation`,
        `timestamp`, etc. Older versions nested them under a `userMetadata` key, so
        we accept both layouts for forward compatibility.
        """
        delta_table = await self.get_delta_table()
        if delta_table is None:
            return False

        history = await asyncio.to_thread(delta_table.history, limit=scan_limit)

        for commit in history:
            if self._commit_matches(commit, match):
                return True

        return False

    @staticmethod
    def _commit_matches(commit: dict[str, Any], match: dict[str, str]) -> bool:
        """Return True iff every (k, v) in `match` is present in this commit's metadata.

        Handles both the flat layout (delta-rs 1.x inlines custom_metadata onto the
        top-level commit dict) and a nested `userMetadata` key (older/other layouts).
        """
        if all(commit.get(k) == v for k, v in match.items()):
            return True

        raw = commit.get("userMetadata")
        if raw is None:
            return False

        if isinstance(raw, str):
            try:
                nested = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                return False
        elif isinstance(raw, dict):
            nested = raw
        else:
            return False

        return all(nested.get(k) == v for k, v in match.items())

    async def has_batch_been_committed(self, run_uuid: str, batch_index: int) -> bool:
        """Check whether a specific (run_uuid, batch_index) has already been committed to delta.

        Thin wrapper around `has_commit_with_metadata` so callers don't need to know
        the metadata schema used for idempotency tagging.
        """
        return await self.has_commit_with_metadata({"run_uuid": run_uuid, "batch_index": str(batch_index)})

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
