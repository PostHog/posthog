from boto3 import resource
from botocore.client import Config

from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
)


def teardown_storage(prefix: str) -> None:
    """Deletes all objects with a given prefix to clean up after tests that write to object storage"""

    s3 = resource(
        "s3",
        endpoint_url=OBJECT_STORAGE_ENDPOINT,
        aws_access_key_id=OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=OBJECT_STORAGE_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )
    bucket = s3.Bucket(OBJECT_STORAGE_BUCKET)
    bucket.objects.filter(Prefix=prefix).delete()
