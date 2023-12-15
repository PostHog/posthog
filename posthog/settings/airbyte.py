import os

AIRBYTE_API_KEY = os.getenv("AIRBYTE_API_KEY", None)
AIRBYTE_BUCKET_REGION = os.getenv("AIRBYTE_BUCKET_REGION", None)
AIRBYTE_BUCKET_KEY = os.getenv("AIRBYTE_BUCKET_KEY", "object_storage_root_user")
AIRBYTE_BUCKET_SECRET = os.getenv("AIRBYTE_BUCKET_SECRET", "object_storage_root_password")
AIRBYTE_BUCKET_DOMAIN = os.getenv("AIRBYTE_BUCKET_DOMAIN", None)
# for DLT
BUCKET_URL = os.getenv("BUCKET_URL", "s3://test-external-data-jobs")
AIRBYTE_BUCKET_NAME = os.getenv("AIRBYTE_BUCKET_NAME", None)
