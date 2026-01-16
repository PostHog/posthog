import json
import time
import uuid
from dataclasses import dataclass, field

from django.conf import settings

import pyarrow as pa
import pyarrow.parquet as pq
from structlog.types import FilteringBoundLogger

from products.data_warehouse.backend.models import ExternalDataJob
from products.data_warehouse.backend.s3 import ensure_bucket_exists, get_s3_client


@dataclass
class BatchWriteResult:
    s3_path: str
    row_count: int
    byte_size: int
    batch_index: int
    timestamp_ns: int = field(default_factory=time.time_ns)


class S3BatchWriter:
    _job: ExternalDataJob
    _schema_id: str
    _logger: FilteringBoundLogger
    _run_uuid: str
    _base_folder: str
    _data_folder: str
    _schema: pa.Schema | None

    def __init__(
        self, logger: FilteringBoundLogger, job: ExternalDataJob, schema_id: str, run_uuid: str | None = None
    ) -> None:
        self._job = job
        self._schema_id = schema_id
        self._logger = logger
        self._run_uuid = (
            run_uuid if run_uuid is not None else f"generated-{str(uuid.uuid4())}"
        )  # in some edge cases the temporal uuid it not available yet
        self._base_folder = self._get_base_folder()
        self._data_folder = f"{self._base_folder}/data"
        self._schema = None

        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        if settings.USE_LOCAL_SETUP:
            if (
                not settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY
                or not settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET
                or not settings.DATAWAREHOUSE_LOCAL_BUCKET_REGION
            ):
                raise KeyError(
                    "Missing env vars for data warehouse. Required vars: DATAWAREHOUSE_LOCAL_ACCESS_KEY, "
                    "DATAWAREHOUSE_LOCAL_ACCESS_SECRET, DATAWAREHOUSE_LOCAL_BUCKET_REGION"
                )

            ensure_bucket_exists(
                settings.BUCKET_URL,
                settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
                settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
                settings.OBJECT_STORAGE_ENDPOINT,
            )

    def _get_base_folder(self) -> str:
        return f"{settings.BUCKET_URL}/data_pipelines_extract/{self._job.team_id}/{self._schema_id}/{self._run_uuid}"  # TODO: decide if we want to add date info in the path

    def write_batch(self, pa_table: pa.Table, batch_index: int) -> BatchWriteResult:
        timestamp_ns = time.time_ns()
        file_name = f"part-{batch_index:04d}.parquet"
        s3_path = f"{self._data_folder}/{file_name}"

        self._logger.debug(
            f"Writing batch {batch_index} to {s3_path}",
            batch_index=batch_index,
            row_count=pa_table.num_rows,
        )

        s3 = get_s3_client()

        s3_path_without_protocol = s3_path.replace("s3://", "")
        with s3.open(s3_path_without_protocol, "wb") as f:
            pq.write_table(pa_table, f, compression="snappy")

        file_info = s3.info(s3_path_without_protocol)
        byte_size = file_info.get("Size", 0) if isinstance(file_info, dict) else 0

        if self._schema is None:
            self._schema = pa_table.schema
        else:
            self._schema = pa.unify_schemas([self._schema, pa_table.schema])

        self._logger.debug(
            f"Batch {batch_index} written successfully",
            s3_path=s3_path,
            row_count=pa_table.num_rows,
            byte_size=byte_size,
        )

        return BatchWriteResult(
            s3_path=s3_path,
            row_count=pa_table.num_rows,
            byte_size=byte_size,
            batch_index=batch_index,
            timestamp_ns=timestamp_ns,
        )

    def write_schema(self) -> str | None:
        if self._schema is None:
            self._logger.debug("No schema to write (no batches were written)")
            return None

        schema_path = f"{self._base_folder}/schema.json"
        s3_path_without_protocol = schema_path.replace("s3://", "")

        schema_dict = {
            "fields": [
                {
                    "name": field.name,
                    "type": str(field.type),
                    "nullable": field.nullable,
                    "metadata": dict(field.metadata) if field.metadata else None,
                }
                for field in self._schema
            ],
            "pandas_metadata": self._schema.pandas_metadata,
        }

        self._logger.debug(f"Writing schema to {schema_path}")

        s3 = get_s3_client()
        with s3.open(s3_path_without_protocol, "w") as f:
            json.dump(schema_dict, f, indent=2)

        self._logger.debug(f"Schema written successfully", s3_path=schema_path)

        return schema_path

    def get_base_folder(self) -> str:
        return self._base_folder

    def get_data_folder(self) -> str:
        return self._data_folder

    def get_run_uuid(self) -> str:
        return self._run_uuid

    def get_schema(self) -> pa.Schema | None:
        return self._schema

    def cleanup(self) -> None:
        s3 = get_s3_client()
        base_folder_without_protocol = self._base_folder.replace("s3://", "")
        try:
            s3.delete(base_folder_without_protocol, recursive=True)
            self._logger.debug(f"Cleaned up extraction folder: {self._base_folder}")
        except FileNotFoundError:
            self._logger.debug(f"Extraction folder not found during cleanup: {self._base_folder}")
