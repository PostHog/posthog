import os
from typing import Optional

from posthog.settings import get_from_env
from posthog.settings.base_variables import DEBUG, TEST
from posthog.settings.utils import str_to_bool

if TEST or DEBUG:
    SESSION_RECORDING_V2_S3_ENDPOINT = os.getenv("SESSION_RECORDING_V2_S3_ENDPOINT", "http://seaweedfs:8333")
    SESSION_RECORDING_V2_S3_ACCESS_KEY_ID: Optional[str] = os.getenv("SESSION_RECORDING_V2_S3_ACCESS_KEY_ID", "any")
    SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY: Optional[str] = os.getenv(
        "SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY", "any"
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

if TEST or DEBUG:
    RECORDING_API_URL = os.getenv("RECORDING_API_URL", "http://localhost:6741")
else:
    RECORDING_API_URL = os.getenv("RECORDING_API_URL", "")

# Dedicated signing secret for the team-scoped JWTs that authorize recording-api calls.
# Kept off SECRET_KEY/JWT_SIGNING_KEY (which are fleet-wide) so only the designated minters
# — Django web and the Python Temporal workers — can mint recording-api tokens. Comma-separated
# `new_key,old_key` for rotation: callers sign with the first key, recording-api verifies against
# all. Dev/test default matches the recording-api Node default so local end-to-end calls validate.
RECORDING_API_JWT_SECRET = os.getenv(
    "RECORDING_API_JWT_SECRET", "dev-recording-api-jwt-secret" if (TEST or DEBUG) else ""
)

# Dedicated signing secret for the tokens that let the replay player fetch fonts and scripts through
# replay.ph-proxy.com (github.com/PostHog/ph-proxy.com). The proxy holds the same keys, so this must
# never be SECRET_KEY or JWT_SIGNING_KEY. Comma-separated `new_key,old_key` for rotation. There is no
# dev default because the source is public: a known key would let anyone mint tokens the proxy accepts.
# Empty means no token, which is what self-hosted installs get.
REPLAY_PROXY_JWT_SECRET = os.getenv("REPLAY_PROXY_JWT_SECRET", "")
