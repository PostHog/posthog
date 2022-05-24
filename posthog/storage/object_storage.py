import abc
from typing import Optional

import structlog
from boto3 import client
from botocore.client import Config
from django.conf import settings

logger = structlog.get_logger(__name__)


class ObjectStorageError(Exception):
    pass


class S3(metaclass=abc.ABCMeta):
    """Just because the full S3 API is available doesn't mean we should use it all"""

    @abc.abstractmethod
    def head_bucket(self, bucket: str) -> bool:
        pass

    @abc.abstractmethod
    def read(self, bucket: str, key: str) -> Optional[str]:
        pass

    @abc.abstractmethod
    def write(self, bucket: str, key: str, content: str) -> None:
        pass


class UnavailableStorage(S3):
    def read(self, bucket: str, key: str) -> Optional[str]:
        pass

    def write(self, bucket: str, key: str, content: str) -> None:
        pass

    def head_bucket(self, bucket: str):
        return False


class ObjectStorage(S3):
    def __init__(self, aws_client, bucket: str) -> None:
        self.aws_client = aws_client

    def head_bucket(self, bucket: str) -> bool:
        try:
            return bool(self.aws_client.head_bucket(bucket=bucket))
        except Exception as e:
            logger.warn("object_storage.health_check_failed", bucket=bucket, error=e)
            return False

    def read(self, bucket: str, key: str) -> Optional[str]:
        s3_response = {}
        try:
            s3_response = self.aws_client.get_object(Bucket=bucket, Key=key)
            content = s3_response["Body"].read()
            return content.decode("utf-8")
        except Exception as e:
            logger.error("object_storage.read_failed", bucket=bucket, file_name=key, error=e, s3_response=s3_response)
            raise ObjectStorageError("read failed") from e

    def write(self, bucket: str, key: str, content: str) -> None:
        s3_response = {}
        try:
            s3_response = self.aws_client.put_object(Bucket=bucket, Body=content, Key=key)
        except Exception as e:
            logger.error("object_storage.write_failed", bucket=bucket, file_name=key, error=e, s3_response=s3_response)
            raise ObjectStorageError("write failed") from e


s3_client: S3 = ObjectStorage(
    client(
        "s3",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
        aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4", connect_timeout=1, retries={"max_attempts": 1}),
        region_name="us-east-1",
    ),
    bucket=settings.OBJECT_STORAGE_BUCKET,
) if settings.OBJECT_STORAGE_ENABLED else UnavailableStorage()


def write(file_name: str, content: str) -> None:
    return s3_client.write(bucket=settings.OBJECT_STORAGE_BUCKET, key=file_name, content=content)


def read(file_name: str) -> Optional[str]:
    return s3_client.read(bucket=settings.OBJECT_STORAGE_BUCKET, key=file_name)


def health_check() -> bool:
    return s3_client.head_bucket(settings.OBJECT_STORAGE_BUCKET)
