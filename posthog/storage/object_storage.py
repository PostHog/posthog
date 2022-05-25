import structlog
from boto3 import client
from botocore.client import Config

logger = structlog.get_logger(__name__)

from django.conf import settings

s3_client = None


# boto doing some magic and gets confused if this is hinted as BaseClient
# noinspection PyMissingTypeHints
def storage_client():
    global s3_client
    if not settings.OBJECT_STORAGE_ENABLED:
        s3_client = None
    elif not s3_client:
        s3_client = client(
            "s3",
            endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
            aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4", connect_timeout=1, retries={"max_attempts": 1}),
            region_name="us-east-1",
        )

    return s3_client


def health_check() -> bool:
    # noinspection PyBroadException
    try:
        client = storage_client()
        response = client.head_bucket(Bucket=settings.OBJECT_STORAGE_BUCKET) if client else False
        return bool(response)
    except Exception as e:
        logger.warn("object_storage.health_check_failed", error=e)
        return False
