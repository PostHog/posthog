import structlog
from boto3 import client
from botocore.client import Config

logger = structlog.get_logger(__name__)

from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
)

s3_client = None


# boto doing some magic and gets confused if this is hinted as BaseClient
# noinspection PyMissingTypeHints
def storage_client():
    global s3_client
    if not s3_client:
        s3_client = client(
            "s3",
            endpoint_url=OBJECT_STORAGE_ENDPOINT,
            aws_access_key_id=OBJECT_STORAGE_ACCESS_KEY_ID,
            aws_secret_access_key=OBJECT_STORAGE_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )
    return s3_client


class ObjectStorageError(Exception):
    pass


def write(file_name: str, content: str):
    s3_response = {}
    try:
        s3_response = storage_client().put_object(Bucket=OBJECT_STORAGE_BUCKET, Body=content, Key=file_name)
    except Exception as e:
        logger.error("object_storage.write_failed", file_name=file_name, error=e, s3_response=s3_response)
        raise ObjectStorageError("write failed") from e


def read(file_name: str):
    s3_response = {}
    try:
        s3_response = storage_client().get_object(Bucket=OBJECT_STORAGE_BUCKET, Key=file_name)
        content = s3_response["Body"].read()
        return content.decode("utf-8")
    except Exception as e:
        logger.error("object_storage.read_failed", file_name=file_name, error=e, s3_response=s3_response)
        raise ObjectStorageError("read failed") from e


def health_check() -> bool:
    # noinspection PyBroadException
    try:
        response = storage_client().head_bucket(Bucket=OBJECT_STORAGE_BUCKET)
        return bool(response)
    except Exception as e:
        logger.warn("object_storage.health_check_failed", error=e)
        return False
