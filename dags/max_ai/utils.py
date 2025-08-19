import hashlib
from collections.abc import Sequence
from contextlib import contextmanager
from datetime import datetime
from tempfile import TemporaryFile

import botocore
from dagster_aws.s3 import S3Resource
from django.conf import settings
from fastavro import parse_schema, writer
from pydantic_avro import AvroBase
from tenacity import retry, stop_after_attempt, wait_exponential

EVALS_S3_PREFIX = "ai_evals"

# objectstorage has only the default bucket in debug.
if settings.DEBUG:
    EVALS_S3_BUCKET = settings.OBJECT_STORAGE_BUCKET
else:
    EVALS_S3_BUCKET = settings.DAGSTER_AI_EVALS_S3_BUCKET


def get_consistent_hash_suffix(file_name: str, date: datetime | None = None, code_version: str | None = None) -> str:
    """
    Generate a consistent hash suffix that updates twice per month based on the filename.

    The hash changes on the 1st and 15th of each month, ensuring links update
    twice monthly while remaining consistent within each period.

    Args:
        file_name: The base filename to hash
        date: Optional date for testing, defaults to current date
        code_version: Optional code version for hash consistency

    Returns:
        A short hash string (8 characters) that's consistent within each half-month period
    """
    if date is None:
        date = datetime.now()

    # Determine which half of the month we're in
    half_month_period = 1 if date.day < 15 else 2

    # Create a seed that changes twice per month
    period_seed = f"{date.year}-{date.month:02d}-{half_month_period}"

    # Combine the period seed with the filename for consistent hashing
    hash_input = f"{period_seed}:{file_name}"
    if code_version:
        hash_input += f":{code_version}"

    # Generate a short, URL-safe hash
    hash_obj = hashlib.sha256(hash_input.encode("utf-8"))
    return hash_obj.hexdigest()[:8]


def compose_postgres_dump_path(project_id: int, dir_name: str, code_version: str | None = None) -> str:
    """Compose S3 path for Postgres dumps with consistent hashing"""
    hash_suffix = get_consistent_hash_suffix(dir_name, code_version=code_version)
    return f"{EVALS_S3_PREFIX}/postgres_models/{project_id}/{dir_name}/{hash_suffix}.avro"


def check_dump_exists(s3: S3Resource, file_key: str) -> bool:
    """Check if a file exists in S3"""
    try:
        s3.get_client().head_object(Bucket=EVALS_S3_BUCKET, Key=file_key)
        return True
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return False
        raise


@contextmanager
def dump_model(*, s3: S3Resource, schema: type[AvroBase], file_key: str):
    with TemporaryFile() as f:
        parsed_schema = parse_schema(schema.avro_schema())

        def dump(models: Sequence[AvroBase]):
            writer(f, parsed_schema, (model.model_dump() for model in models))

        yield dump

        @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=4))
        def upload():
            f.seek(0)
            s3.get_client().upload_fileobj(f, EVALS_S3_BUCKET, file_key)

        upload()
