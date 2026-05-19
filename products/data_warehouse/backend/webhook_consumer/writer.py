import uuid
from typing import Literal, cast

from django.conf import settings

import pyarrow as pa
import structlog
import pyarrow.parquet as pq

from posthog.temporal.data_imports.pipelines.pipeline_v3.s3.common import ensure_bucket, strip_s3_protocol

from products.data_warehouse.backend.s3 import get_s3_client

logger = structlog.get_logger(__name__)

PARQUET_SCHEMA = pa.schema(
    cast(
        "list[tuple[str, pa.DataType]]",
        [
            ("team_id", pa.int64()),
            ("schema_id", pa.utf8()),
            ("payload_json", pa.utf8()),
        ],
    )
)


class WebhookParquetWriter:
    def __init__(self, compression: Literal["gzip", "bz2", "brotli", "lz4", "zstd", "snappy", "none"] = "zstd"):
        self._compression = compression
        self._s3 = get_s3_client()
        ensure_bucket()

    def write(self, table: pa.Table, team_id: int, schema_id: str) -> str:
        file_uuid = str(uuid.uuid4())
        s3_path = (
            f"s3://{settings.DATAWAREHOUSE_BUCKET}/source_webhook_producer/{team_id}/{schema_id}/{file_uuid}.parquet"
        )
        path_without_protocol = strip_s3_protocol(s3_path)

        with self._s3.open(path_without_protocol, "wb") as f:
            pq.write_table(table.cast(PARQUET_SCHEMA), f, compression=self._compression)

        logger.debug(
            "webhook_parquet_written",
            s3_path=s3_path,
            team_id=team_id,
            schema_id=schema_id,
            row_count=table.num_rows,
        )

        return s3_path
