import abc
from typing import Optional, Union

import structlog
from boto3 import client
from botocore.client import Config
from django.conf import settings
from sentry_sdk import capture_exception

logger = structlog.get_logger(__name__)


class ObjectStorageError(Exception):
    pass


class ObjectStorageClient(metaclass=abc.ABCMeta):
    """Just because the full S3 API is available doesn't mean we should use it all"""

    @abc.abstractmethod
    def head_bucket(self, bucket: str) -> bool:
        pass

    @abc.abstractmethod
    def read(self, bucket: str, key: str) -> Optional[str]:
        pass

    @abc.abstractmethod
    def read_bytes(self, bucket: str, key: str) -> Optional[bytes]:
        pass

    @abc.abstractmethod
    def write(self, bucket: str, key: str, content: Union[str, bytes]) -> None:
        pass


class UnavailableStorage(ObjectStorageClient):
    def head_bucket(self, bucket: str):
        return False

    def read(self, bucket: str, key: str) -> Optional[str]:
        pass

    def read_bytes(self, bucket: str, key: str) -> Optional[bytes]:
        pass

    def write(self, bucket: str, key: str, content: Union[str, bytes]) -> None:
        pass


class ObjectStorage(ObjectStorageClient):
    def __init__(self, aws_client) -> None:
        self.aws_client = aws_client

    def head_bucket(self, bucket: str) -> bool:
        try:
            return bool(self.aws_client.head_bucket(Bucket=bucket))
        except Exception as e:
            logger.warn("object_storage.health_check_failed", bucket=bucket, error=e)
            return False

    def read(self, bucket: str, key: str) -> Optional[str]:
        object_bytes = self.read_bytes(bucket, key)
        if object_bytes:
            return object_bytes.decode("utf-8")
        else:
            return None

    def read_bytes(self, bucket: str, key: str) -> Optional[bytes]:
        s3_response = {}
        try:
            s3_response = self.aws_client.get_object(Bucket=bucket, Key=key)
            return s3_response["Body"].read()
        except Exception as e:
            logger.error("object_storage.read_failed", bucket=bucket, file_name=key, error=e, s3_response=s3_response)
            capture_exception(e)
            raise ObjectStorageError("read failed") from e

    def write(self, bucket: str, key: str, content: Union[str, bytes]) -> None:
        s3_response = {}
        try:
            s3_response = self.aws_client.put_object(Bucket=bucket, Body=content, Key=key)
        except Exception as e:
            logger.error("object_storage.write_failed", bucket=bucket, file_name=key, error=e, s3_response=s3_response)
            capture_exception(e)
            raise ObjectStorageError("write failed") from e


_client: ObjectStorageClient = UnavailableStorage()


def object_storage_client() -> ObjectStorageClient:
    global _client

    if not settings.OBJECT_STORAGE_ENABLED:
        _client = UnavailableStorage()
    elif isinstance(_client, UnavailableStorage):
        _client = ObjectStorage(
            client(
                "s3",
                endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
                aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
                aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
                config=Config(signature_version="s3v4", connect_timeout=1, retries={"max_attempts": 1}),
                region_name="us-east-1",
            ),
        )

    return _client


def write(file_name: str, content: Union[str, bytes]) -> None:
    return object_storage_client().write(bucket=settings.OBJECT_STORAGE_BUCKET, key=file_name, content=content)


def read(file_name: str) -> Optional[str]:
    return object_storage_client().read(bucket=settings.OBJECT_STORAGE_BUCKET, key=file_name)


def read_bytes(file_name: str) -> Optional[bytes]:
    return object_storage_client().read_bytes(bucket=settings.OBJECT_STORAGE_BUCKET, key=file_name)


def health_check() -> bool:
    return object_storage_client().head_bucket(bucket=settings.OBJECT_STORAGE_BUCKET)
