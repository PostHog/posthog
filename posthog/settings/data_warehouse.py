import os

from posthog.settings.utils import get_from_env, str_to_bool

AIRBYTE_API_KEY = os.getenv("AIRBYTE_API_KEY", None)
AIRBYTE_BUCKET_REGION = os.getenv("AIRBYTE_BUCKET_REGION", None)
AIRBYTE_BUCKET_KEY = os.getenv("AIRBYTE_BUCKET_KEY", None)
AIRBYTE_BUCKET_SECRET = os.getenv("AIRBYTE_BUCKET_SECRET", None)
AIRBYTE_BUCKET_DOMAIN = os.getenv("AIRBYTE_BUCKET_DOMAIN", None)
# for DLT
BUCKET_URL = os.getenv("BUCKET_URL", None)
AIRBYTE_BUCKET_NAME = os.getenv("AIRBYTE_BUCKET_NAME", None)
BUCKET = "test-pipeline"

PYARROW_DEBUG_LOGGING = get_from_env("PYARROW_DEBUG_LOGGING", False, type_cast=str_to_bool)
