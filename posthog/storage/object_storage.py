import abc
from queue import Queue
from threading import Thread
from typing import List, Optional, Tuple, Union

import structlog
from boto3 import client
from botocore.client import Config
from django.conf import settings

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
    def list_all_objects(self, bucket: str, prefix: str) -> List[dict]:
        pass

    @abc.abstractmethod
    def read_all(self, bucket: str, keys: List[str], max_concurrent_requests: int) -> List[Tuple[str, str]]:
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

    def list_all_objects(self, bucket: str, prefix: str) -> List[dict]:
        pass

    def read_all(self, bucket: str, keys: List[str], max_concurrent_requests: int) -> List[Tuple[str, str]]:
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
            raise ObjectStorageError("read failed") from e

    def list_all_objects(self, bucket: str, prefix: str) -> List[dict]:
        objects: List[dict] = []
        try:
            has_next = True
            while has_next:
                last_key = objects[-1]["Key"] if len(objects) > 0 else ""
                s3_response = self.aws_client.list_objects_v2(
                    Bucket=bucket, Prefix=prefix, Delimiter="/", StartAfter=last_key
                )
                has_next = s3_response["IsTruncated"]
                objects.extend(s3_response["Contents"])
            return objects
        except Exception as e:
            logger.error("object_storage.list_all_objects_failed", bucket=bucket, prefix=prefix, error=e)
            raise ObjectStorageError("list_all_objects failed") from e

    def _read_from_queue_for_threading(
        self, keys_queue: Queue, bucket: str, result_list: List[Tuple[str, Optional[str]]]
    ):
        while not keys_queue.empty():
            (key_index, key) = keys_queue.get()
            result_list[key_index] = (key, self.read(bucket, key))

    def read_all(self, bucket: str, keys: List[str], max_concurrent_requests: int) -> List[Tuple[str, str]]:
        keys_queue: Queue[Tuple[int, str]] = Queue()
        for index, key in enumerate(keys):
            keys_queue.put((index, key))
        threads: list[Thread] = []
        results_list: List[Optional[Tuple[str, str]]] = [None] * len(keys)
        for _ in range(max_concurrent_requests):
            thread = Thread(
                target=self._read_from_queue_for_threading, args=(keys_queue, bucket, results_list), daemon=True,
            )
            thread.start()
            threads.append(thread)

        for t in threads:
            t.join()

        return results_list  # type: ignore

    def write(self, bucket: str, key: str, content: Union[str, bytes]) -> None:
        s3_response = {}
        try:
            s3_response = self.aws_client.put_object(Bucket=bucket, Body=content, Key=key)
        except Exception as e:
            logger.error("object_storage.write_failed", bucket=bucket, file_name=key, error=e, s3_response=s3_response)
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
                config=Config(
                    signature_version="s3v4", connect_timeout=1, retries={"max_attempts": 1}, max_pool_connections=10
                ),
                region_name="us-east-1",
            ),
        )

    return _client


def write(file_name: str, content: Union[str, bytes]) -> None:
    return object_storage_client().write(bucket=settings.OBJECT_STORAGE_BUCKET, key=file_name, content=content)


def read(file_name: str) -> Optional[str]:
    return object_storage_client().read(bucket=settings.OBJECT_STORAGE_BUCKET, key=file_name)


def list_all_objects(prefix: str) -> Optional[List[dict]]:
    return object_storage_client().list_all_objects(bucket=settings.OBJECT_STORAGE_BUCKET, prefix=prefix)


def read_all(file_names: List[str], max_concurrent_requests: int = 10) -> Optional[List[Tuple[str, str]]]:
    return object_storage_client().read_all(
        bucket=settings.OBJECT_STORAGE_BUCKET, keys=file_names, max_concurrent_requests=max_concurrent_requests
    )


def read_bytes(file_name: str) -> Optional[bytes]:
    return object_storage_client().read_bytes(bucket=settings.OBJECT_STORAGE_BUCKET, key=file_name)


def health_check() -> bool:
    return object_storage_client().head_bucket(bucket=settings.OBJECT_STORAGE_BUCKET)
