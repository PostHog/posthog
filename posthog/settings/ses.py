import os
from typing import Optional

from posthog.settings.base_variables import DEBUG, TEST
from posthog.settings.utils import get_from_env
from posthog.utils import str_to_bool

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

# SNS topics allowed to deliver SES tenant reputation events (EventBridge -> SNS -> webhook).
# Empty (the default) leaves the webhook inert: the SNS signature proves a message came from AWS,
# but only the allowlist proves it came from *our* topic.
WORKFLOWS_SES_EVENTS_SNS_TOPIC_ARNS: list[str] = [
    arn.strip() for arn in os.getenv("WORKFLOWS_SES_EVENTS_SNS_TOPIC_ARNS", "").split(",") if arn.strip()
]

# Automatic per-workflow email pause. The detector sweeps every workflow's spam-complaint and
# hard-bounce rates and pauses the ones that breach a threshold, because all workflow email shares
# one SES account and one bad workflow drags deliverability down for every customer.
#
# Off by default. While off, the detector logs what it would have paused and increments its
# counter, but writes nothing, which is how the thresholds below get calibrated per region before
# anything enforces.
WORKFLOW_EMAIL_AUTO_PAUSE_ENABLED: bool = get_from_env(
    "WORKFLOW_EMAIL_AUTO_PAUSE_ENABLED", False, type_cast=str_to_bool
)

# Volume gates. A workflow that sent 12 emails and drew 1 complaint is a 8% complaint rate and
# no information, so a breach needs both enough sends in the window and enough feedback events.
WORKFLOW_EMAIL_AUTO_PAUSE_MIN_SENT_1H: int = get_from_env("WORKFLOW_EMAIL_AUTO_PAUSE_MIN_SENT_1H", 200, type_cast=int)
WORKFLOW_EMAIL_AUTO_PAUSE_MIN_SENT_24H: int = get_from_env(
    "WORKFLOW_EMAIL_AUTO_PAUSE_MIN_SENT_24H", 1000, type_cast=int
)

# Complaint thresholds sit below AWS's account danger zone (about 0.1% draws warnings and about
# 0.5% risks enforcement) because a single workflow held at 0.3% measurably drags the shared
# account down.
WORKFLOW_EMAIL_AUTO_PAUSE_COMPLAINT_MIN_EVENTS_1H: int = get_from_env(
    "WORKFLOW_EMAIL_AUTO_PAUSE_COMPLAINT_MIN_EVENTS_1H", 5, type_cast=int
)
WORKFLOW_EMAIL_AUTO_PAUSE_COMPLAINT_RATE_1H: float = get_from_env(
    "WORKFLOW_EMAIL_AUTO_PAUSE_COMPLAINT_RATE_1H", 0.01, type_cast=float
)
WORKFLOW_EMAIL_AUTO_PAUSE_COMPLAINT_MIN_EVENTS_24H: int = get_from_env(
    "WORKFLOW_EMAIL_AUTO_PAUSE_COMPLAINT_MIN_EVENTS_24H", 10, type_cast=int
)
WORKFLOW_EMAIL_AUTO_PAUSE_COMPLAINT_RATE_24H: float = get_from_env(
    "WORKFLOW_EMAIL_AUTO_PAUSE_COMPLAINT_RATE_24H", 0.003, type_cast=float
)

# Hard-bounce thresholds mirror AWS's own bounce guidance: 5% warn, 10% enforce.
WORKFLOW_EMAIL_AUTO_PAUSE_BOUNCE_MIN_EVENTS_1H: int = get_from_env(
    "WORKFLOW_EMAIL_AUTO_PAUSE_BOUNCE_MIN_EVENTS_1H", 20, type_cast=int
)
WORKFLOW_EMAIL_AUTO_PAUSE_BOUNCE_RATE_1H: float = get_from_env(
    "WORKFLOW_EMAIL_AUTO_PAUSE_BOUNCE_RATE_1H", 0.10, type_cast=float
)
WORKFLOW_EMAIL_AUTO_PAUSE_BOUNCE_MIN_EVENTS_24H: int = get_from_env(
    "WORKFLOW_EMAIL_AUTO_PAUSE_BOUNCE_MIN_EVENTS_24H", 50, type_cast=int
)
WORKFLOW_EMAIL_AUTO_PAUSE_BOUNCE_RATE_24H: float = get_from_env(
    "WORKFLOW_EMAIL_AUTO_PAUSE_BOUNCE_RATE_24H", 0.05, type_cast=float
)

# Warning band: at these rates the workflow's admins get a heads-up email, and at the pause rates
# above the workflow's email stops. Half the pause rate, with the same volume gates, so a warning
# always precedes a slow-burning pause while an acute burst can still pause without one.
WORKFLOW_EMAIL_WARN_COMPLAINT_RATE_1H: float = get_from_env(
    "WORKFLOW_EMAIL_WARN_COMPLAINT_RATE_1H", 0.005, type_cast=float
)
WORKFLOW_EMAIL_WARN_COMPLAINT_RATE_24H: float = get_from_env(
    "WORKFLOW_EMAIL_WARN_COMPLAINT_RATE_24H", 0.0015, type_cast=float
)
WORKFLOW_EMAIL_WARN_BOUNCE_RATE_1H: float = get_from_env("WORKFLOW_EMAIL_WARN_BOUNCE_RATE_1H", 0.05, type_cast=float)
WORKFLOW_EMAIL_WARN_BOUNCE_RATE_24H: float = get_from_env("WORKFLOW_EMAIL_WARN_BOUNCE_RATE_24H", 0.025, type_cast=float)

# How long one warning covers a workflow. Without this bound the hourly detector would repeat the
# same email every run while the workflow sits inside the warning band.
WORKFLOW_EMAIL_WARN_COOLDOWN_DAYS: int = get_from_env("WORKFLOW_EMAIL_WARN_COOLDOWN_DAYS", 7, type_cast=int)
