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

# SNS topics allowed to deliver SES tenant reputation events (EventBridge -> SNS -> webhook).
# Empty (the default) leaves the webhook inert: the SNS signature proves a message came from AWS,
# but only the allowlist proves it came from *our* topic.
WORKFLOWS_SES_EVENTS_SNS_TOPIC_ARNS: list[str] = [
    arn.strip() for arn in os.getenv("WORKFLOWS_SES_EVENTS_SNS_TOPIC_ARNS", "").split(",") if arn.strip()
]

# SES ISP dimension values to break sending health down by. The only API that names providers is
# GetDomainStatisticsReport, which needs the Deliverability dashboard subscription, so the list
# comes from us. These names are read off the VDM dashboard's ISP table, which reports the same
# dimension SES matches queries on, so each one is known to exist rather than guessed.
#
# SES validates the format only and accepts any well-formed word, inventions included. A name it
# has no data for is therefore harmless: it costs one query set and yields no row, because
# providers with zero sends are dropped. A name holding "." or "&" is not harmless. SES rejects
# "Mail.ru", "Web.de" and "AT&T" with BadRequestException, which fails every query sent in the
# same request, not just the one holding the name. So check a new value against the API before
# adding it: query SEND for the name over a window VDM has data for, and treat volume as the only
# proof the name is real.
#
# Each name also adds one query per metric per domain to a fan-out that runs inside a web request
# under METRIC_QUERY_BUDGET_SECONDS, so weigh a new provider against that budget.
SES_ISP_DIMENSIONS: list[str] = [
    "Gmail",
    "Hotmail",
    "ExchangeOnline",
    "Yahoo",
    "Icloud",
    "Aol",
    "Comcast",
    "Gmx",
    "Tencent",
    "NetEase",
    # The dashboard's catch-all row. Whether SES accepts it as a query dimension is unconfirmed:
    # it may be a label for sends it could not attribute rather than a value it matches on.
    "Unknown ISP",
]
