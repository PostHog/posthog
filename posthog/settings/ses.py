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

# Calls a minute PostHog allows itself against the account-wide SESv2 ListRecommendations quota,
# shared by the reputation poller, the tenant reconciliation sweep, and the Reputation tab. See
# posthog/egress/ses/limiter.py for how the share is split between them.
SES_RECOMMENDATIONS_EGRESS_PER_MINUTE_BUDGET = int(os.getenv("SES_RECOMMENDATIONS_EGRESS_PER_MINUTE_BUDGET", "45"))

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

# SES ISP dimension values to break sending health down by. The only API that names providers is
# GetDomainStatisticsReport, which needs the Deliverability dashboard subscription, so the list
# comes from us, and SES gives no way to check a name up front: it validates the format only, and
# accepts any well-formed word, inventions included. Two consequences.
#
# A name SES has no data for is harmless. It costs one query set and yields no row, because
# providers with zero sends are dropped. That is why both spellings are listed for the two
# families whose SES name is unconfirmed, Microsoft and Apple: the right one wins and the other
# disappears. Prune the losers once VDM has collected.
#
# A name holding "." or "&" is not harmless. SES rejects "Mail.ru", "Web.de" and "AT&T" with
# BadRequestException, which fails the whole BatchGetMetricData request and hides the entire
# breakdown rather than one row. Those are plausible providers to reach for, so check a new value
# against the API before adding it: query SEND for the name over a window VDM has data for, and
# treat volume as the only proof the name is real.
SES_ISP_DIMENSIONS: list[str] = ["Gmail", "Yahoo", "Outlook", "Hotmail", "Apple", "iCloud"]
