import json
import time
import uuid

import pyarrow as pa
import pyarrow.parquet as pq
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.pipelines.pipeline_v3.s3.common import (
    BatchWriteResult,
    cleanup_folder,
    ensure_bucket,
    get_base_folder,
    get_data_folder,
    strip_s3_protocol,
)

from products.data_warehouse.backend.models import ExternalDataJob
from products.data_warehouse.backend.s3 import get_s3_client


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
        if run_uuid is not None:
            self._run_uuid = run_uuid
        else:
            self._run_uuid = f"generated-{str(uuid.uuid4())}"
            self._logger.warning("S3BatchWriter: No run_uuid provided, using generated UUID", run_uuid=self._run_uuid)
        self._base_folder = get_base_folder(self._job.team_id, self._schema_id, self._run_uuid)
        self._data_folder = get_data_folder(self._base_folder)
        self._schema = None

        ensure_bucket()

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

        s3_path_without_protocol = strip_s3_protocol(s3_path)
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
        s3_path_without_protocol = strip_s3_protocol(schema_path)

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
        cleanup_folder(self._base_folder)
        self._logger.debug(f"Cleaned up extraction folder: {self._base_folder}")
