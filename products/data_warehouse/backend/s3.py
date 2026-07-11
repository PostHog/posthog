import contextlib
from typing import Optional
from urllib.parse import urlparse

from django.conf import settings

import s3fs
import boto3
import botocore
import botocore.exceptions


def get_s3_client():
    # Defaults for localhost dev and test suites
    if settings.USE_LOCAL_SETUP:
        return s3fs.S3FileSystem(
            key=settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
            secret=settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
            endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
            # skip_instance_cache ensures a fresh S3FileSystem instance is created each time,
            # avoiding "Event loop is closed" errors when the event loop changes between async
            # operations (e.g., between test modules with module-scoped event loops).
            skip_instance_cache=True,
        )

    return s3fs.S3FileSystem()


@contextlib.asynccontextmanager
async def aget_s3_client(*, fresh_instance: bool = False):
    # fresh_instance=True bypasses the fsspec instance cache: a new S3FileSystem bound to the current
    # event loop, closed on context exit. The cached default hands every caller the same instance
    # regardless of loop, so async_to_sync-driven code (each call runs on a fresh, short-lived loop)
    # gets an aiobotocore client bound to an already-closed loop ("Event loop is closed") and a
    # dircache that goes stale whenever delta-rs writes to S3 through its own object store behind
    # s3fs's back. Reserve it for low-frequency, correctness-critical paths (repartition purge/swap):
    # every fresh instance pays connection setup + credential resolution, so defaulting it on would
    # hammer the credential provider from hot paths.
    uncached = fresh_instance or settings.USE_LOCAL_SETUP
    if settings.USE_LOCAL_SETUP:
        # Defaults for localhost dev and test suites. skip_instance_cache avoids "Event loop is
        # closed" errors when the loop changes between test modules.
        s3 = s3fs.S3FileSystem(
            key=settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
            secret=settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
            endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
            skip_instance_cache=True,
            asynchronous=True,
        )
    else:
        s3 = s3fs.S3FileSystem(asynchronous=True, skip_instance_cache=fresh_instance)

    await s3.set_session()

    if not uncached:
        yield s3
        return

    try:
        yield s3
    finally:
        # Uncached instances aren't finalized by the fsspec registry, so close the aiobotocore client
        # explicitly (s3fs's set_session docs: "to be closed later with await .close()") to avoid
        # leaking HTTP connections in long-lived workers. Never close the shared cached instance —
        # other callers hold references to it.
        with contextlib.suppress(Exception):
            if s3._s3 is not None:
                await s3._s3.close()


def get_size_of_folder(path: str) -> float:
    s3 = get_s3_client()

    files = s3.find(path, detail=True)
    file_values = files.values() if isinstance(files, dict) else files

    total_bytes = sum(f["Size"] for f in file_values if f["type"] != "directory")
    total_mib = total_bytes / (1024 * 1024)

    return total_mib


def ensure_bucket_exists(s3_url: str, s3_key: str, s3_secret: str, s3_endpoint: Optional[str] = None) -> None:
    s3_client = boto3.client("s3", aws_access_key_id=s3_key, aws_secret_access_key=s3_secret, endpoint_url=s3_endpoint)

    parsed = urlparse(s3_url)
    if parsed.scheme != "s3":
        raise ValueError(f"Invalid S3 URL: {s3_url}")

    bucket_name = parsed.netloc

    try:
        s3_client.head_bucket(Bucket=bucket_name)
    except botocore.exceptions.ClientError as e:
        error = e.response.get("Error")
        if not error:
            raise

        error_code = error.get("Code")
        if not error_code:
            raise

        if int(error_code) == 404:
            s3_client.create_bucket(Bucket=bucket_name)
        else:
            raise
