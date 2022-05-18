from boto3 import client, resource
from botocore.client import Config
from botocore.exceptions import EndpointConnectionError

from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_HOST,
    OBJECT_STORAGE_PORT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
)

s3 = resource(
    "s3",
    endpoint_url=f"http://{OBJECT_STORAGE_HOST}:{OBJECT_STORAGE_PORT}",
    aws_access_key_id=OBJECT_STORAGE_ACCESS_KEY_ID,
    aws_secret_access_key=OBJECT_STORAGE_SECRET_ACCESS_KEY,
    config=Config(signature_version="s3v4"),
    region_name="us-east-1",
)

client = client(
    "s3",
    endpoint_url=f"http://{OBJECT_STORAGE_HOST}:{OBJECT_STORAGE_PORT}",
    aws_access_key_id=OBJECT_STORAGE_ACCESS_KEY_ID,
    aws_secret_access_key=OBJECT_STORAGE_SECRET_ACCESS_KEY,
    config=Config(signature_version="s3v4"),
    region_name="us-east-1",
)


def health_check() -> bool:
    try:
        response = client.head_bucket(Bucket=OBJECT_STORAGE_BUCKET)
        if response:
            return True
        else:
            return False
    except (client.exceptions.NoSuchBucket, EndpointConnectionError) as e:
        return False
