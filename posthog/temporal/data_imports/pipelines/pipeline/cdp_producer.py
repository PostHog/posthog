import json

from django.conf import settings

import orjson
import pyarrow as pa
import pyarrow.fs as pa_fs
import pyarrow.parquet as pq
from pyarrow.parquet import write_table
from structlog.types import FilteringBoundLogger

from posthog.schema import DatabaseSchemaDataWarehouseTable

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database

from posthog.exceptions_capture import capture_exception
from posthog.kafka_client.client import KafkaProducer
from posthog.kafka_client.topics import KAFKA_DWH_CDP_RAW_TABLE
from posthog.models.hog_functions import HogFunction

from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
from products.data_warehouse.backend.s3 import ensure_bucket_exists, get_s3_client


class CDPProducer:
    team_id: int
    schema_id: str
    job_id: str
    logger: FilteringBoundLogger

    def __init__(self, team_id: int, schema_id: str, job_id: str, logger: FilteringBoundLogger) -> None:
        self.team_id = team_id
        self.schema_id = schema_id
        self.job_id = job_id
        self.logger = logger

    def _get_fs(self) -> pa_fs.S3FileSystem:
        if settings.USE_LOCAL_SETUP:
            ensure_bucket_exists(
                f"s3://{self._get_path_prefix()}",
                settings.AIRBYTE_BUCKET_KEY,
                settings.AIRBYTE_BUCKET_SECRET,
                settings.OBJECT_STORAGE_ENDPOINT,
            )

            return pa_fs.S3FileSystem(
                access_key=settings.AIRBYTE_BUCKET_KEY,
                secret_key=settings.AIRBYTE_BUCKET_SECRET,
                endpoint_override=settings.OBJECT_STORAGE_ENDPOINT,
            )

        return pa_fs.S3FileSystem(access_key=settings.AIRBYTE_BUCKET_KEY, secret_key=settings.AIRBYTE_BUCKET_SECRET)

    def _get_path_prefix(self) -> str:
        return f"{settings.DATAWAREHOUSE_BUCKET}/cdp_producer/{self.team_id}/{self.schema_id}/{self.job_id}"

    def _list_files_to_produce(self) -> list[str]:
        s3_client = get_s3_client()
        ls_res = s3_client.ls(f"s3://{self._get_path_prefix()}/", detail=True)
        ls_values = ls_res.values() if isinstance(ls_res, dict) else ls_res
        files = [f["Key"] for f in ls_values if f["type"] != "directory"]

        return files

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

    @property
    def should_produce_table(self) -> bool:
        schema = ExternalDataSchema.objects.get(id=self.schema_id, team_id=self.team_id)
        table_id = str(schema.table_id)
        if table_id is None:
            raise ValueError(f"CDPProducer: Schema {schema.name} ({self.schema_id}) does not have a table_id")

        hogql_database = Database.create_for(team_id=self.team_id)
        serialized_db = hogql_database.serialize(HogQLContext(team_id=self.team_id, database=hogql_database))
        tables = [
            n for n in serialized_db.values() if isinstance(n, DatabaseSchemaDataWarehouseTable) and n.id == table_id
        ]
        table = tables[0] if tables else None
        if table is None:
            raise ValueError(f"CDPProducer: Table {table_id} (schema: {schema.name}) not found in hogql database")

        self.logger.debug(f"Checking if table {table.name} is used in any HogQL functions")
        self.logger.debug(f"Using table_name = {table.name}, source = data-warehouse")

        return HogFunction.objects.filter(
            team_id=self.team_id,
            filters__source="data-warehouse",
            filters__data_warehouse__contains=[{"table_name": table.name}],
        ).exists()

    def clear_s3_chunks(self):
        fs = self._get_fs()
        self.logger.debug(f"Clearing S3 chunks at path prefix {self._get_path_prefix()}")
        fs.delete_dir(self._get_path_prefix())

    def write_chunk_for_cdp_producer(self, chunk: int, table: pa.Table) -> None:
        s3_fs = self._get_fs()

        self.logger.debug(f"Writing chunk {chunk} for CDP producer to S3 path prefix {self._get_path_prefix()}")

        write_table(
            table,
            f"{self._get_path_prefix()}/chunk_{chunk}.parquet",
            filesystem=s3_fs,
            compression="zstd",
            use_dictionary=True,
        )

    def produce_to_kafka_from_s3(self) -> None:
        fs = self._get_fs()

        self.logger.debug(f"Producing CDP data to Kafka from S3 path prefix {self._get_path_prefix()}")

        files_to_produce = self._list_files_to_produce()

        self.logger.debug(f"Found {len(files_to_produce)} files to produce to Kafka")

        for file_path in files_to_produce:
            self.logger.debug(f"Producing file {file_path} to Kafka")

            try:
                with fs.open_input_file(file_path) as f:
                    pf = pq.ParquetFile(f)

                    for index, batch in enumerate(pf.iter_batches(batch_size=10_000)):
                        self.logger.debug(f"Producing batch {index} from file {file_path} to Kafka")

                        for row in batch.to_pylist():
                            row_as_props = {"team_id": self.team_id, "properties": row}
                            KafkaProducer().produce(
                                topic=KAFKA_DWH_CDP_RAW_TABLE, data=row_as_props, value_serializer=self._serialize_json
                            )

                self.logger.debug(f"Finished producing file {file_path} to Kafka")
                self.logger.debug(f"Deleting file {file_path}")

                fs.delete_file(file_path)
            except Exception as e:
                capture_exception(e)
                self.logger.exception(f"Error producing file {file_path} to Kafka: {e}")

        self.logger.debug("Finished producing all CDP data to Kafka")
