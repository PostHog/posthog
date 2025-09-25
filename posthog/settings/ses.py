import os
from typing import Optional

from posthog.settings import get_from_env
from posthog.settings.base_variables import DEBUG, TEST
from posthog.utils import str_to_bool

if TEST or DEBUG:
    SES_ENDPOINT = os.getenv("SES_ENDPOINT", "http://localhost:4566")
    SES_ACCESS_KEY_ID: Optional[str] = os.getenv("SES_ACCESS_KEY_ID", "test")
    SES_SECRET_ACCESS_KEY: Optional[str] = os.getenv("SES_SECRET_ACCESS_KEY", "test")
else:
    SES_ENDPOINT = os.getenv("SES_ENDPOINT", "")
    SES_ACCESS_KEY_ID = os.getenv("SES_ACCESS_KEY_ID", "") or None
    SES_SECRET_ACCESS_KEY = os.getenv("SES_SECRET_ACCESS_KEY", "") or None

SES_ENABLED = get_from_env("SES_ENABLED", True if DEBUG else False, type_cast=str_to_bool)
SES_REGION = os.getenv("SES_REGION", "us-east-1")
