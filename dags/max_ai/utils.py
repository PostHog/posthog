import hashlib
from datetime import datetime

from django.conf import settings


def get_consistent_hash_suffix(file_name: str, date: datetime | None = None, code_version: str | None = None) -> str:
    """
    Generate a consistent hash suffix that updates twice per month based on the filename.

    The hash changes on the 1st and 15th of each month, ensuring links update
    twice monthly while remaining consistent within each period.

    Args:
        file_name: The base filename to hash
        date: Optional date for testing, defaults to current date

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


def compose_postgres_dump_path(project_id: int, file_name: str, code_version: str | None = None) -> str:
    """Compose S3 path for Postgres dumps with consistent hashing"""
    hash_suffix = get_consistent_hash_suffix(file_name, code_version=code_version)
    versioned_file_name = f"{file_name}_{hash_suffix}"
    return f"{settings.OBJECT_STORAGE_MAX_AI_EVALS_FOLDER}/models/{project_id}/{versioned_file_name}.avro"
