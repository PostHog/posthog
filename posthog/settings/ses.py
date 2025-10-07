import os
from typing import Optional

from posthog.settings.base_variables import DEBUG, TEST

if TEST or DEBUG:
    SES_ENDPOINT = os.getenv("SES_ENDPOINT", "http://localhost:4566")
    SES_ACCESS_KEY_ID: Optional[str] = os.getenv("SES_ACCESS_KEY_ID", "test")
    SES_SECRET_ACCESS_KEY: Optional[str] = os.getenv("SES_SECRET_ACCESS_KEY", "test")
else:
    SES_ENDPOINT = os.getenv("SES_ENDPOINT", "")
    SES_ACCESS_KEY_ID = os.getenv("SES_ACCESS_KEY_ID", "") or None
    SES_SECRET_ACCESS_KEY = os.getenv("SES_SECRET_ACCESS_KEY", "") or None

SES_REGION = os.getenv("SES_REGION", "us-east-1")
