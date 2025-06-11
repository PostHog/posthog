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


def get_size_of_folder(path: str) -> float:
    s3 = get_s3_client()

    files = s3.find(path, detail=True)
    file_values = files.values() if isinstance(files, dict) else files

    total_bytes = sum(f["Size"] for f in file_values if f["type"] != "directory")
    total_mib = total_bytes / (1024 * 1024)

    return total_mib
