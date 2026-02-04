import time
from dataclasses import dataclass, field

from django.conf import settings

import structlog

from products.data_warehouse.backend.s3 import ensure_bucket_exists, get_s3_client

logger = structlog.get_logger(__name__)


@dataclass
class BatchWriteResult:
    """Result of writing a batch to S3."""

    s3_path: str
    row_count: int
    byte_size: int
    batch_index: int
    timestamp_ns: int = field(default_factory=time.time_ns)


def strip_s3_protocol(s3_path: str) -> str:
    """Remove the s3:// protocol prefix from a path."""
    return s3_path.replace("s3://", "")


def get_base_folder(team_id: int, schema_id: str, run_uuid: str) -> str:
    """Get the base S3 folder path for a pipeline run."""
    return f"{settings.BUCKET_URL}/data_pipelines_extract/{team_id}/{schema_id}/{run_uuid}"


def get_data_folder(base_folder: str) -> str:
    """Get the data folder path within a base folder."""
    return f"{base_folder}/data"


def ensure_bucket() -> None:
    """Ensure the S3 bucket exists for local development."""
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


def cleanup_folder(folder_path: str) -> None:
    """Delete an S3 folder and all its contents."""
    s3 = get_s3_client()
    folder_without_protocol = strip_s3_protocol(folder_path)
    try:
        s3.delete(folder_without_protocol, recursive=True)
        logger.debug("cleanup_folder_success", folder=folder_path)
    except FileNotFoundError:
        logger.debug("cleanup_folder_not_found", folder=folder_path)
