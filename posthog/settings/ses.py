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

# Configuration sets referenced by workflow email sends. With tenant attribution, SES requires
# every resource a send references — the configuration set included, not just the sending
# identity — to be associated with the tenant, so provisioning associates these with each tenant.
# KEEP IN SYNC with the Node email worker's SES_TRACKED_CONFIGURATION_SET /
# SES_UNTRACKED_CONFIGURATION_SET (nodejs/src/cdp/config.ts and the cdp-cyclotron-worker-email
# chart): there is no shared config between the two services, so a set the worker sends through
# but which is missing here never gets associated and attributed sends through it fail.
SES_TENANT_CONFIGURATION_SETS: list[str] = [
    cs.strip()
    for cs in os.getenv("SES_TENANT_CONFIGURATION_SETS", "posthog-messaging,posthog-messaging-untracked").split(",")
    if cs.strip()
]
