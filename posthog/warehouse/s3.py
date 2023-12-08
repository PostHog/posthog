import s3fs
from django.conf import settings


def get_s3_client():
    return s3fs.S3FileSystem(
        key=settings.AIRBYTE_BUCKET_KEY,
        secret=settings.AIRBYTE_BUCKET_SECRET,
    )
