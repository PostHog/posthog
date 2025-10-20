import os
from typing import Optional

from posthog.settings import get_from_env
from posthog.settings.base_variables import DEBUG, TEST
from posthog.settings.utils import str_to_bool

if TEST or DEBUG:
    SESSION_RECORDING_V2_S3_ENDPOINT = os.getenv("SESSION_RECORDING_V2_S3_ENDPOINT", "http://objectstorage:19000")
    SESSION_RECORDING_V2_S3_ACCESS_KEY_ID: Optional[str] = os.getenv(
        "SESSION_RECORDING_V2_S3_ACCESS_KEY_ID", "object_storage_root_user"
    )
    SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY: Optional[str] = os.getenv(
        "SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY", "object_storage_root_password"
    )
else:
    SESSION_RECORDING_V2_S3_ENDPOINT = os.getenv("SESSION_RECORDING_V2_S3_ENDPOINT", "")
    # To enable us to specify that the AWS provided credentials for e.g. the EC2
    # or Fargate task, we default to `None` rather than "" as this will, when
    # passed to boto, result in the correct credentials being used.
    SESSION_RECORDING_V2_S3_ACCESS_KEY_ID = os.getenv("SESSION_RECORDING_V2_S3_ACCESS_KEY_ID", "") or None
    SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY = os.getenv("SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY", "") or None

SESSION_RECORDING_V2_S3_ENABLED = get_from_env(
    "SESSION_RECORDING_V2_S3_ENABLED", True if DEBUG else False, type_cast=str_to_bool
)
SESSION_RECORDING_V2_S3_REGION = os.getenv("SESSION_RECORDING_V2_S3_REGION", "us-east-1")
SESSION_RECORDING_V2_S3_BUCKET = os.getenv("SESSION_RECORDING_V2_S3_BUCKET", "posthog")
SESSION_RECORDING_V2_S3_PREFIX = os.getenv("SESSION_RECORDING_V2_S3_PREFIX", "session_recordings")
SESSION_RECORDING_V2_S3_LTS_PREFIX = os.getenv("SESSION_RECORDING_V2_S3_LTS_PREFIX", "session_recordings/saved/1y")
