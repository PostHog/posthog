import s3fs
from django.conf import settings
from posthog.settings.base_variables import TEST


def get_s3_client():
    if TEST:
        return s3fs.S3FileSystem(
            key=settings.AIRBYTE_BUCKET_KEY,
            secret=settings.AIRBYTE_BUCKET_SECRET,
            endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
        )

    return s3fs.S3FileSystem(
        key=settings.AIRBYTE_BUCKET_KEY,
        secret=settings.AIRBYTE_BUCKET_SECRET,
    )
