import abc
import structlog
from boto3 import client as boto3_client
from botocore.client import Config
from django.conf import settings

logger = structlog.get_logger(__name__)


class SessionRecordingV2ObjectStorageBase(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def read_bytes(self, key: str, first_byte: int, last_byte: int) -> bytes | None:
        pass


class UnavailableSessionRecordingV2ObjectStorage(SessionRecordingV2ObjectStorageBase):
    def read_bytes(self, key: str, first_byte: int, last_byte: int) -> bytes | None:
        return None


class SessionRecordingV2ObjectStorage(SessionRecordingV2ObjectStorageBase):
    def __init__(self, aws_client, bucket: str) -> None:
        self.aws_client = aws_client
        self.bucket = bucket

    def read_bytes(self, key: str, first_byte: int, last_byte: int) -> bytes | None:
        s3_response = {}
        try:
            kwargs = {
                "Bucket": self.bucket,
                "Key": key,
                "Range": f"bytes={first_byte}-{last_byte}",
            }
            s3_response = self.aws_client.get_object(**kwargs)
            return s3_response["Body"].read()
        except Exception as e:
            logger.exception(
                "session_recording_v2_object_storage.read_failed",
                bucket=self.bucket,
                file_name=key,
                error=e,
                s3_response=s3_response,
            )
            return None


_client: SessionRecordingV2ObjectStorageBase = UnavailableSessionRecordingV2ObjectStorage()


def client() -> SessionRecordingV2ObjectStorageBase:
    global _client

    required_settings = [
        settings.SESSION_RECORDING_V2_S3_ENDPOINT,
        settings.SESSION_RECORDING_V2_S3_REGION,
        settings.SESSION_RECORDING_V2_S3_BUCKET,
    ]

    if not all(required_settings):
        _client = UnavailableSessionRecordingV2ObjectStorage()
    elif isinstance(_client, UnavailableSessionRecordingV2ObjectStorage):
        _client = SessionRecordingV2ObjectStorage(
            boto3_client(
                "s3",
                endpoint_url=settings.SESSION_RECORDING_V2_S3_ENDPOINT,
                aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
                aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
                config=Config(
                    signature_version="s3v4",  # type: ignore[attr-defined]
                    connect_timeout=1,  # type: ignore[attr-defined]
                    retries={"max_attempts": 1},  # type: ignore[attr-defined]
                ),
                region_name=settings.SESSION_RECORDING_V2_S3_REGION,
            ),
            bucket=settings.SESSION_RECORDING_V2_S3_BUCKET,
        )

    return _client
