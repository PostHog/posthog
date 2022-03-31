"""
Helpers to interact with our Object Storage system
"""
import datetime
from typing import Dict, List

import boto3
from botocore.client import Config

# TODO: we should pass to our client the compressed file and then decompress in the browser
from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_HOST,
    OBJECT_STORAGE_PORT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
)

s3 = boto3.resource(
    "s3",
    endpoint_url=f"http://{OBJECT_STORAGE_HOST}:{OBJECT_STORAGE_PORT}",
    aws_access_key_id=OBJECT_STORAGE_ACCESS_KEY_ID,
    aws_secret_access_key=OBJECT_STORAGE_SECRET_ACCESS_KEY,
    config=Config(signature_version="s3v4"),
    region_name="us-east-1",
)

client = boto3.client(
    "s3",
    endpoint_url=f"http://{OBJECT_STORAGE_HOST}:{OBJECT_STORAGE_PORT}",
    aws_access_key_id=OBJECT_STORAGE_ACCESS_KEY_ID,
    aws_secret_access_key=OBJECT_STORAGE_SECRET_ACCESS_KEY,
    config=Config(signature_version="s3v4"),
    region_name="us-east-1",
)


def write(file_name: str, content: str):
    s3.Bucket(OBJECT_STORAGE_BUCKET).put_object(Body=content, Key=file_name)


def read(file_name: str):
    s3_object = s3.Object(OBJECT_STORAGE_BUCKET, file_name)
    content = s3_object.get()["Body"].read()
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
    paginator = client.get_paginator("list_objects")
    prefix = _ensure_ends_with_slash(prefix)
    return paginator.paginate(Bucket=OBJECT_STORAGE_BUCKET, Prefix=prefix, Delimiter="/").search("CommonPrefixes")


def delete_older_than(date_limit: datetime.date, prefix: str) -> int:
    """
    Finds the top level buckets in the given prefix
    Each of those bucket names that can be converted to a date is deleted
    if its name is a date older than the provided date_limit
    """
    count = 0
    for bucket_key in page_buckets(prefix):
        try:
            folder_date_key = bucket_key["Prefix"].replace(prefix, "")[:-1]
            folder_date_key = _ensure_no_slashes(folder_date_key)
            folder_date: datetime.date = datetime.datetime.strptime(folder_date_key, "%Y-%m-%d").date()
            if folder_date < date_limit:
                old_bucket = s3.Object(OBJECT_STORAGE_BUCKET, f"{prefix}/{folder_date_key}")
                old_bucket.delete()  # deletes the entire bucket in one operation
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
