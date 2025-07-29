import abc
from typing import Optional, Union, Any

import structlog
from boto3 import client
from botocore.client import Config
from django.conf import settings
from posthog.exceptions_capture import capture_exception

logger = structlog.get_logger(__name__)


class ObjectStorageError(Exception):
    pass


class ObjectStorageClient(metaclass=abc.ABCMeta):
    """Just because the full S3 API is available doesn't mean we should use it all"""

    @abc.abstractmethod
    def head_bucket(self, bucket: str) -> bool:
        pass

    @abc.abstractmethod
    def head_object(self, bucket: str, file_key: str) -> Optional[dict]:
        pass

    @abc.abstractmethod
    def get_presigned_url(self, bucket: str, file_key: str, expiration: int = 3600) -> Optional[str]:
        pass

    @abc.abstractmethod
    def get_presigned_post(
        self, bucket: str, file_key: str, conditions: list[Any], expiration: int = 3600
    ) -> Optional[dict]:
        pass

    @abc.abstractmethod
    def list_objects(self, bucket: str, prefix: str) -> Optional[list[str]]:
        pass

    @abc.abstractmethod
    def read(self, bucket: str, key: str) -> Optional[str]:
        pass

    @abc.abstractmethod
    def read_bytes(self, bucket: str, key: str) -> Optional[bytes]:
        pass

    @abc.abstractmethod
    def tag(self, bucket: str, key: str, tags: dict[str, str]) -> None:
        pass

    @abc.abstractmethod
    def write(self, bucket: str, key: str, content: Union[str, bytes], extras: dict | None) -> None:
        pass

    @abc.abstractmethod
    def copy_objects(self, bucket: str, source_prefix: str, target_prefix: str) -> int | None:
        """
        Copy objects from one prefix to another. Returns the number of objects copied.
        """
        pass

    @abc.abstractmethod
    def delete(self, bucket: str, key: str) -> None:
        pass


class UnavailableStorage(ObjectStorageClient):
    def head_bucket(self, bucket: str):
        return False

    def head_object(self, bucket: str, file_key: str):
        return None

    def get_presigned_url(self, bucket: str, file_key: str, expiration: int = 3600) -> Optional[str]:
        pass

    def get_presigned_post(
        self, bucket: str, file_key: str, conditions: list[Any], expiration: int = 3600
    ) -> Optional[dict]:
        pass

    def list_objects(self, bucket: str, prefix: str) -> Optional[list[str]]:
        pass

    def read(self, bucket: str, key: str) -> Optional[str]:
        return None

    def read_bytes(self, bucket: str, key: str) -> Optional[bytes]:
        return None

    def tag(self, bucket: str, key: str, tags: dict[str, str]) -> None:
        pass

    def write(self, bucket: str, key: str, content: Union[str, bytes], extras: dict | None) -> None:
        pass

    def copy_objects(self, bucket: str, source_prefix: str, target_prefix: str) -> int | None:
        pass

    def delete(self, bucket: str, key: str) -> None:
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

    def head_object(self, bucket: str, file_key) -> Optional[dict]:
        try:
            return self.aws_client.head_object(Bucket=bucket, Key=file_key)
        except Exception as e:
            logger.warn("object_storage.head_object_failed", bucket=bucket, file_key=file_key, error=e)
            return None

    def get_presigned_url(self, bucket: str, file_key: str, expiration: int = 3600) -> Optional[str]:
        try:
            return self.aws_client.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": bucket, "Key": file_key},
                ExpiresIn=expiration,
                HttpMethod="GET",
            )
        except Exception as e:
            logger.exception("object_storage.get_presigned_url_failed", file_name=file_key, error=e)
            capture_exception(e)
            return None

    def get_presigned_post(
        self, bucket: str, file_key: str, conditions: list[Any], expiration: int = 3600
    ) -> Optional[dict]:
        try:
            return self.aws_client.generate_presigned_post(
                bucket, file_key, Conditions=conditions, ExpiresIn=expiration
            )
        except Exception as e:
            logger.exception("object_storage.get_presigned_post_failed", file_name=file_key, error=e)
            capture_exception(e)
            return None

    def list_objects(self, bucket: str, prefix: str) -> Optional[list[str]]:
        try:
            s3_response = self.aws_client.list_objects_v2(Bucket=bucket, Prefix=prefix)
            if s3_response.get("Contents"):
                return [obj["Key"] for obj in s3_response["Contents"]]
            else:
                return None
        except Exception as e:
            logger.exception(
                "object_storage.list_objects_failed",
                bucket=bucket,
                prefix=prefix,
                error=e,
            )
            capture_exception(e)
            return None

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
            logger.exception(
                "object_storage.read_failed",
                bucket=bucket,
                file_name=key,
                error=e,
                s3_response=s3_response,
            )
            capture_exception(e)
            raise ObjectStorageError("read failed") from e

    def tag(self, bucket: str, key: str, tags: dict[str, str]) -> None:
        try:
            self.aws_client.put_object_tagging(
                Bucket=bucket,
                Key=key,
                Tagging={"TagSet": [{"Key": k, "Value": v} for k, v in tags.items()]},
            )
        except Exception as e:
            logger.exception("object_storage.tag_failed", bucket=bucket, file_name=key, error=e)
            capture_exception(e)
            raise ObjectStorageError("tag failed") from e

    def write(self, bucket: str, key: str, content: Union[str, bytes], extras: dict | None) -> None:
        s3_response = {}
        try:
            s3_response = self.aws_client.put_object(Bucket=bucket, Body=content, Key=key, **(extras or {}))
        except Exception as e:
            logger.exception(
                "object_storage.write_failed",
                bucket=bucket,
                file_name=key,
                error=e,
                s3_response=s3_response,
            )
            capture_exception(e)
            raise ObjectStorageError("write failed") from e

    def copy_objects(self, bucket: str, source_prefix: str, target_prefix: str) -> int | None:
        try:
            source_objects = self.list_objects(bucket, source_prefix) or []

            for object_key in source_objects:
                copy_source = {"Bucket": bucket, "Key": object_key}
                target = object_key.replace(source_prefix.rstrip("/"), target_prefix)
                self.aws_client.copy(copy_source, bucket, target)

            return len(source_objects)
        except Exception as e:
            logger.exception(
                "object_storage.copy_objects_failed",
                source_prefix=source_prefix,
                target_prefix=target_prefix,
                error=e,
            )
            capture_exception(e)
            return None

    def delete(self, bucket: str, key: str) -> None:
        response = {}
        try:
            response = self.aws_client.delete_object(Bucket=bucket, Key=key)
        except Exception as e:
            logger.exception("object_storage.delete_failed", bucket=bucket, key=key, error=e, s3_response=response)
            capture_exception(e)
            raise ObjectStorageError("delete failed") from e


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
                config=Config(
                    signature_version="s3v4",
                    connect_timeout=1,
                    retries={"max_attempts": 1},
                ),
                region_name=settings.OBJECT_STORAGE_REGION,
            )
        )

    return _client


def write(file_name: str, content: Union[str, bytes], extras: dict | None = None, bucket: str | None = None) -> None:
    return object_storage_client().write(
        bucket=bucket or settings.OBJECT_STORAGE_BUCKET,
        key=file_name,
        content=content,
        extras=extras,
    )


def delete(file_name: str, bucket: str | None = None) -> None:
    return object_storage_client().delete(bucket=bucket or settings.OBJECT_STORAGE_BUCKET, key=file_name)


def tag(file_name: str, tags: dict[str, str]) -> None:
    return object_storage_client().tag(bucket=settings.OBJECT_STORAGE_BUCKET, key=file_name, tags=tags)


def read(file_name: str, bucket: str | None = None) -> Optional[str]:
    return object_storage_client().read(bucket=bucket or settings.OBJECT_STORAGE_BUCKET, key=file_name)


def read_bytes(file_name: str, bucket: str | None = None) -> Optional[bytes]:
    bucket = bucket or settings.OBJECT_STORAGE_BUCKET
    return object_storage_client().read_bytes(bucket, file_name)


def list_objects(prefix: str) -> Optional[list[str]]:
    return object_storage_client().list_objects(bucket=settings.OBJECT_STORAGE_BUCKET, prefix=prefix)


def copy_objects(source_prefix: str, target_prefix: str) -> int:
    return (
        object_storage_client().copy_objects(
            bucket=settings.OBJECT_STORAGE_BUCKET,
            source_prefix=source_prefix,
            target_prefix=target_prefix,
        )
        or 0
    )


def get_presigned_url(file_key: str, expiration: int = 3600) -> Optional[str]:
    return object_storage_client().get_presigned_url(
        bucket=settings.OBJECT_STORAGE_BUCKET, file_key=file_key, expiration=expiration
    )


def get_presigned_post(file_key: str, conditions: list[Any], expiration: int = 3600) -> Optional[dict]:
    return object_storage_client().get_presigned_post(
        bucket=settings.OBJECT_STORAGE_BUCKET, file_key=file_key, conditions=conditions, expiration=expiration
    )


def head_object(file_key: str, bucket: str = settings.OBJECT_STORAGE_BUCKET) -> Optional[dict]:
    return object_storage_client().head_object(file_key=file_key, bucket=bucket)


def health_check() -> bool:
    return object_storage_client().head_bucket(bucket=settings.OBJECT_STORAGE_BUCKET)
