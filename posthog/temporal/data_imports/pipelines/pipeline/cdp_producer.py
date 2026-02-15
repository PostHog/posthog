import json
import asyncio

from django.conf import settings

import orjson
import pyarrow as pa
import pyarrow.fs as pa_fs
import pyarrow.parquet as pq
from pyarrow.parquet import write_table
from structlog.types import FilteringBoundLogger

from posthog.hogql.database.database import get_data_warehouse_table_name

from posthog.exceptions_capture import capture_exception
from posthog.models.hog_functions import HogFunction
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.data_imports.pipelines.helpers import build_table_name

from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
from products.data_warehouse.backend.s3 import aget_s3_client, ensure_bucket_exists


class FakeKafka:
    def produce(self, *args, **kwargs):
        pass

    def flush(self, *args, **kwargs):
        pass


class CDPProducer:
    team_id: int
    schema_id: str
    job_id: str
    logger: FilteringBoundLogger
    _should_produce_cache: bool | None

    def __init__(self, team_id: int, schema_id: str, job_id: str, logger: FilteringBoundLogger) -> None:
        self.team_id = team_id
        self.schema_id = schema_id
        self.job_id = job_id
        self.logger = logger
        self._should_produce_cache = None

    def _get_fs(self) -> pa_fs.S3FileSystem:
        if settings.USE_LOCAL_SETUP:
            ensure_bucket_exists(
                f"s3://{self._get_path_prefix()}",
                settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
                settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
                settings.OBJECT_STORAGE_ENDPOINT,
            )

            return pa_fs.S3FileSystem(
                access_key=settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
                secret_key=settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
                endpoint_override=settings.OBJECT_STORAGE_ENDPOINT,
            )

        return pa_fs.S3FileSystem()

    def _get_path_prefix(self) -> str:
        return f"{settings.DATAWAREHOUSE_BUCKET}/cdp_producer/{self.team_id}/{self.schema_id}/{self.job_id}"

    async def _list_files_to_produce(self) -> list[str]:
        async with aget_s3_client() as s3_client:
            try:
                ls_res = await s3_client._ls(f"s3://{self._get_path_prefix()}/", detail=True)
                ls_values = ls_res.values() if isinstance(ls_res, dict) else ls_res
                files = [f["Key"] for f in ls_values if f["type"] != "directory"]
                return files
            except FileNotFoundError:
                return []

    def _serialize_json(self, record: object) -> bytes:
        try:
            return orjson.dumps(record)
        except TypeError:
            try:
                return json.dumps(record).encode("utf-8")
            except Exception as e:
                if isinstance(record, dict):
                    record = {str(k): str(v) for k, v in record.items()}
                    return json.dumps(record).encode("utf-8")

                raise ValueError("Could not serialize record to JSON") from e

    async def should_produce_table(self) -> bool:
        if self._should_produce_cache is not None:
            return self._should_produce_cache

        @database_sync_to_async_pool
        def _check():
            schema = ExternalDataSchema.objects.get(id=self.schema_id, team_id=self.team_id)

            raw_table_name = build_table_name(schema.source, schema.name)
            dot_notated_table_name = get_data_warehouse_table_name(schema.source, raw_table_name)

            self.logger.debug(f"Checking if table {dot_notated_table_name} is used in any HogQL functions")
            self.logger.debug(f"Using table_name = {dot_notated_table_name}, source = data-warehouse-table")

            return (
                HogFunction.objects.filter(
                    team_id=self.team_id,
                    enabled=True,
                    filters__source="data-warehouse-table",
                    filters__data_warehouse__contains=[{"table_name": dot_notated_table_name}],
                )
                .exclude(deleted=True)
                .exists()
            )

        self._should_produce_cache = await _check()
        return self._should_produce_cache

    async def clear_s3_chunks(self):
        async with aget_s3_client() as s3_client:
            await self.logger.adebug(f"Clearing S3 chunks at path prefix {self._get_path_prefix()}")

            if len(await self._list_files_to_produce()) > 0:
                try:
                    await s3_client._rm(f"s3://{self._get_path_prefix()}/", recursive=True)
                except FileNotFoundError:
                    pass

    async def write_chunk_for_cdp_producer(self, chunk: int, table: pa.Table) -> None:
        await self.logger.adebug(f"Writing chunk {chunk} for CDP producer to S3 path prefix {self._get_path_prefix()}")

        # Write operations in pyarrow are CPU-bound, so run in thread pool
        await asyncio.to_thread(
            write_table,
            table,
            f"{self._get_path_prefix()}/chunk_{chunk}.parquet",
            filesystem=self._get_fs(),
            compression="zstd",
            use_dictionary=True,
        )

    def _kafka_producer(self) -> FakeKafka:
        return FakeKafka()

    async def produce_to_kafka_from_s3(self) -> None:
        fs = self._get_fs()

        await self.logger.adebug(f"Producing CDP data to Kafka from S3 path prefix {self._get_path_prefix()}")

        files_to_produce = await self._list_files_to_produce()

        await self.logger.adebug(f"Found {len(files_to_produce)} files to produce to Kafka")

        kafka_producer = self._kafka_producer()

        for file_path in files_to_produce:
            await self.logger.adebug(f"Producing file {file_path} to Kafka")

            row_index = 0

            try:
                # File I/O operations run in thread pool
                def _process_file(file_path: str) -> int:
                    local_row_index = 0
                    with fs.open_input_file(file_path) as f:
                        pf = pq.ParquetFile(f)

                        for batch in pf.iter_batches(batch_size=10_000):
                            for row in batch.to_pylist():
                                row_as_props = {"team_id": self.team_id, "properties": row}
                                kafka_producer.produce(
                                    topic="", data=row_as_props, value_serializer=self._serialize_json
                                )
                                local_row_index += 1

                    kafka_producer.flush()
                    return local_row_index

                row_index = await asyncio.to_thread(_process_file, file_path)
                await self.logger.adebug(f"Finished producing file {file_path} to Kafka")
            except Exception as e:
                capture_exception(e)
                await self.logger.adebug(f"Error producing file {file_path} to Kafka: {e}")
            finally:
                # TODO(Gilbert09): have better row tracking so we can retry from a particular row
                await self.logger.adebug(f"Produced {row_index} rows")
                await self.logger.adebug(f"Deleting file {file_path}")
                await asyncio.to_thread(fs.delete_file, file_path)

        await self.logger.adebug("Finished producing all CDP data to Kafka")
