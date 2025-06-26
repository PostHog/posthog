import os
from typing import Optional

from posthog.settings import get_from_env
from posthog.settings.base_variables import DEBUG, TEST
from posthog.utils import str_to_bool

if TEST or DEBUG:
    OBJECT_STORAGE_ENDPOINT = os.getenv("OBJECT_STORAGE_ENDPOINT", "http://objectstorage:19000")
    OBJECT_STORAGE_ACCESS_KEY_ID: Optional[str] = os.getenv("OBJECT_STORAGE_ACCESS_KEY_ID", "object_storage_root_user")
    OBJECT_STORAGE_SECRET_ACCESS_KEY: Optional[str] = os.getenv(
        "OBJECT_STORAGE_SECRET_ACCESS_KEY", "object_storage_root_password"
    )
else:
    OBJECT_STORAGE_ENDPOINT = os.getenv("OBJECT_STORAGE_ENDPOINT", "")
    # To enable us to specify that the AWS provided credentials for e.g. the EC2
    # or Fargate task, we default to `None` rather than "" as this will, when
    # passed to boto, result in the correct credentials being used.
    OBJECT_STORAGE_ACCESS_KEY_ID = os.getenv("OBJECT_STORAGE_ACCESS_KEY_ID", "") or None
    OBJECT_STORAGE_SECRET_ACCESS_KEY = os.getenv("OBJECT_STORAGE_SECRET_ACCESS_KEY", "") or None

OBJECT_STORAGE_ENABLED = get_from_env("OBJECT_STORAGE_ENABLED", True if DEBUG else False, type_cast=str_to_bool)
OBJECT_STORAGE_REGION = os.getenv("OBJECT_STORAGE_REGION", "us-east-1")
OBJECT_STORAGE_BUCKET = os.getenv("OBJECT_STORAGE_BUCKET", "posthog")
OBJECT_STORAGE_SESSION_RECORDING_BLOB_INGESTION_FOLDER = os.getenv(
    "OBJECT_STORAGE_SESSION_RECORDING_BLOB_INGESTION_FOLDER", "session_recordings"
)
OBJECT_STORAGE_SESSION_RECORDING_LTS_FOLDER = os.getenv(
    "OBJECT_STORAGE_SESSION_RECORDING_LTS_FOLDER", "session_recordings_lts"
)
OBJECT_STORAGE_EXPORTS_FOLDER = os.getenv("OBJECT_STORAGE_EXPORTS_FOLDER", "exports")
OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER = os.getenv("OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER", "media_uploads")
OBJECT_STORAGE_ERROR_TRACKING_SOURCE_MAPS_FOLDER = os.getenv(
    "OBJECT_STORAGE_ERROR_TRACKING_SOURCE_MAPS_FOLDER", "symbolsets"
)
OBJECT_STORAGE_EXTERNAL_WEB_ANALYTICS_BUCKET = os.getenv("OBJECT_STORAGE_EXTERNAL_WEB_ANALYTICS_BUCKET", "posthog")
