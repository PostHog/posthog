import os
from typing import Optional

from posthog.settings.base_variables import DEBUG, TEST

# S3-compatible store holding managed-migration trial run output (browsable
# JSONL pages + summary), written by the batch-import worker (its TRIAL_BUCKET_*
# config must point at the same bucket/prefix) and read back by the API. Retention
# is enforced by an S3 lifecycle rule on the prefix, not by the application.
if TEST or DEBUG:
    MANAGED_MIGRATIONS_TRIAL_S3_ENDPOINT = os.getenv("MANAGED_MIGRATIONS_TRIAL_S3_ENDPOINT", "http://seaweedfs:8333")
    MANAGED_MIGRATIONS_TRIAL_S3_ACCESS_KEY_ID: Optional[str] = os.getenv(
        "MANAGED_MIGRATIONS_TRIAL_S3_ACCESS_KEY_ID", "any"
    )
    MANAGED_MIGRATIONS_TRIAL_S3_SECRET_ACCESS_KEY: Optional[str] = os.getenv(
        "MANAGED_MIGRATIONS_TRIAL_S3_SECRET_ACCESS_KEY", "any"
    )
else:
    MANAGED_MIGRATIONS_TRIAL_S3_ENDPOINT = os.getenv("MANAGED_MIGRATIONS_TRIAL_S3_ENDPOINT", "")
    # Default to None (not "") so boto falls back to the ambient AWS credentials
    # (IRSA / instance role) in production.
    MANAGED_MIGRATIONS_TRIAL_S3_ACCESS_KEY_ID = os.getenv("MANAGED_MIGRATIONS_TRIAL_S3_ACCESS_KEY_ID", "") or None
    MANAGED_MIGRATIONS_TRIAL_S3_SECRET_ACCESS_KEY = (
        os.getenv("MANAGED_MIGRATIONS_TRIAL_S3_SECRET_ACCESS_KEY", "") or None
    )

MANAGED_MIGRATIONS_TRIAL_S3_REGION = os.getenv("MANAGED_MIGRATIONS_TRIAL_S3_REGION", "us-east-1")
# Empty bucket outside DEBUG/TEST means trial results are unavailable (the API
# responds accordingly); set it wherever the worker fleet has a trial bucket.
MANAGED_MIGRATIONS_TRIAL_S3_BUCKET = os.getenv("MANAGED_MIGRATIONS_TRIAL_S3_BUCKET", "posthog" if TEST or DEBUG else "")
MANAGED_MIGRATIONS_TRIAL_S3_PREFIX = os.getenv("MANAGED_MIGRATIONS_TRIAL_S3_PREFIX", "trial_runs")
