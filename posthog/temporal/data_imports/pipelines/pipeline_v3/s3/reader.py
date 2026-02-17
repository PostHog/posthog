import pyarrow as pa
import structlog
import pyarrow.parquet as pq

from posthog.temporal.data_imports.pipelines.pipeline_v3.s3.common import strip_s3_protocol

from products.data_warehouse.backend.s3 import get_s3_client

logger = structlog.get_logger(__name__)


def read_parquet(s3_path: str) -> pa.Table:
    s3 = get_s3_client()
    s3_path_without_protocol = strip_s3_protocol(s3_path)

    logger.debug("reading_parquet", s3_path=s3_path)

    with s3.open(s3_path_without_protocol, "rb") as f:
        table = pq.read_table(f)

    logger.debug("parquet_read_success", s3_path=s3_path, row_count=table.num_rows)

    return table


def list_parquet_files(data_folder: str) -> list[str]:
    s3 = get_s3_client()
    folder_without_protocol = strip_s3_protocol(data_folder)

    try:
        files = s3.ls(folder_without_protocol)
        parquet_files = [f"s3://{f}" for f in files if f.endswith(".parquet")]
        parquet_files.sort()

        logger.debug("list_parquet_files", data_folder=data_folder, file_count=len(parquet_files))

        return parquet_files
    except FileNotFoundError:
        logger.debug("data_folder_not_found", data_folder=data_folder)
        return []


def read_all_batches(data_folder: str) -> pa.Table:
    parquet_files = list_parquet_files(data_folder)

    if not parquet_files:
        logger.debug("no_parquet_files_found", data_folder=data_folder)
        return pa.table({})

    tables = [read_parquet(f) for f in parquet_files]

    if len(tables) == 1:
        return tables[0]

    combined = pa.concat_tables(tables)
    logger.debug("batches_combined", data_folder=data_folder, total_rows=combined.num_rows, batch_count=len(tables))

    return combined
