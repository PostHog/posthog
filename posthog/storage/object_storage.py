from datetime import datetime
from typing import Dict, List

import structlog
from boto3 import client, resource
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
        # see https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html#S3.Client
        s3_client = client(
            "s3",
            endpoint_url=OBJECT_STORAGE_ENDPOINT,
            aws_access_key_id=OBJECT_STORAGE_ACCESS_KEY_ID,
            aws_secret_access_key=OBJECT_STORAGE_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )
    return s3_client


def health_check() -> bool:
    # noinspection PyBroadException
    try:
        response = storage_client().head_bucket(Bucket=OBJECT_STORAGE_BUCKET)
        return bool(response)
    except Exception as e:
        logger.warn("object_storage.health_check_failed", error=e)
        return False


def write(file_name: str, content: str):
    storage_client().put_object(Bucket=OBJECT_STORAGE_BUCKET, Body=content, Key=file_name)


def read(file_name: str):
    body = storage_client().get_object(Bucket=OBJECT_STORAGE_BUCKET, Key=file_name)
    content = body.read()
    return content.decode("utf-8")


def page_buckets(prefix: str) -> List[Dict]:
    """
    For a given bucket prefix in the toplevel posthog bucket
    Finds the buckets it contains

    e.g. for bucket
    posthog/A

    that contains

    posthog/A/1
    posthog/A/2

    if called with prefix "A" it would return [{Prefix: 1}, {Prefix: 2}]
    """
    paginator = storage_client().get_paginator("list_objects")
    prefix = _ensure_ends_with_slash(prefix)
    return paginator.paginate(Bucket=OBJECT_STORAGE_BUCKET, Prefix=prefix, Delimiter="/").search("CommonPrefixes")


def delete_older_than(date_limit: datetime.date, prefix: str) -> int:
    """
    Finds the top level buckets in the given prefix
    Each of those bucket names that can be converted to a date
    is deleted if its name is a date older than the provided date_limit
    """

    s3 = resource(
        "s3",
        endpoint_url=OBJECT_STORAGE_ENDPOINT,
        aws_access_key_id=OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=OBJECT_STORAGE_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )

    count = 0
    for bucket_key in page_buckets(prefix):
        try:
            folder_date_key = bucket_key["Prefix"].replace(prefix, "")[:-1]
            folder_date_key = _ensure_no_slashes(folder_date_key)
            folder_date: datetime.date = datetime.strptime(folder_date_key, "%Y-%m-%d").date()
            if folder_date < date_limit:
                old_folder = s3.Bucket(OBJECT_STORAGE_BUCKET).objects.filter(Prefix=f"{prefix}/{folder_date_key}")
                old_folder.delete()
                count += 1
        except ValueError:
            # the bucket name can't be cast to a date
            # we ignore it
            pass

    return count


def _ensure_no_slashes(name: str) -> str:
    if name[0] == "/":
        name = name[1:]

    if name[:-1] == "/":
        name = name[0:-1]

    return name


def _ensure_ends_with_slash(name: str) -> str:
    if name[:-1] != "/":
        name = name + "/"
    return name
