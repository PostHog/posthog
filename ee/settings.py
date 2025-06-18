"""
Django settings for PostHog Enterprise Edition.
"""

import os

from posthog.settings import AUTHENTICATION_BACKENDS, DEBUG, DEMO, SITE_URL
from posthog.settings.utils import get_from_env
from posthog.utils import str_to_bool

# SSO
AUTHENTICATION_BACKENDS = [
    *AUTHENTICATION_BACKENDS,
    "ee.api.authentication.MultitenantSAMLAuth",
    "ee.api.authentication.CustomGoogleOAuth2",
]

# SAML base attributes
SOCIAL_AUTH_SAML_SP_ENTITY_ID = SITE_URL
SOCIAL_AUTH_SAML_SECURITY_CONFIG = {
    "wantAttributeStatement": False,  # AttributeStatement is optional in the specification
    "requestedAuthnContext": False,  # do not explicitly request a password login, also allow multifactor and others
}
# Attributes below are required for the SAML integration from social_core to work properly
SOCIAL_AUTH_SAML_SP_PUBLIC_CERT = ""
SOCIAL_AUTH_SAML_SP_PRIVATE_KEY = ""
SOCIAL_AUTH_SAML_ORG_INFO = {"en-US": {"name": "posthog", "displayname": "PostHog", "url": "https://posthog.com"}}
SOCIAL_AUTH_SAML_TECHNICAL_CONTACT = {
    "givenName": "PostHog Support",
    "emailAddress": "hey@posthog.com",
}
SOCIAL_AUTH_SAML_SUPPORT_CONTACT = SOCIAL_AUTH_SAML_TECHNICAL_CONTACT


# Google SSO
SOCIAL_AUTH_GOOGLE_OAUTH2_KEY = os.getenv("SOCIAL_AUTH_GOOGLE_OAUTH2_KEY")
SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET = os.getenv("SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET")
if "SOCIAL_AUTH_GOOGLE_OAUTH2_WHITELISTED_DOMAINS" in os.environ:
    SOCIAL_AUTH_GOOGLE_OAUTH2_WHITELISTED_DOMAINS: list[str] = os.environ[
        "SOCIAL_AUTH_GOOGLE_OAUTH2_WHITELISTED_DOMAINS"
    ].split(",")
elif DEMO:
    # Only PostHog team members can use social auth in the demo environment
    # This is because in the demo env social signups get is_staff=True to facilitate instance management
    SOCIAL_AUTH_GOOGLE_OAUTH2_WHITELISTED_DOMAINS = ["posthog.com"]

CUSTOMER_IO_API_KEY = get_from_env("CUSTOMER_IO_API_KEY", "", type_cast=str)
CUSTOMER_IO_API_URL = get_from_env("CUSTOMER_IO_API_URL", "https://api-eu.customer.io", type_cast=str)

# Schedule to run column materialization on. Follows crontab syntax.
# Use empty string to prevent from materializing
MATERIALIZE_COLUMNS_SCHEDULE_CRON = get_from_env("MATERIALIZE_COLUMNS_SCHEDULE_CRON", "0 5 * * SAT")
# Minimum query time before a query if considered for optimization by adding materialized columns
MATERIALIZE_COLUMNS_MINIMUM_QUERY_TIME = get_from_env("MATERIALIZE_COLUMNS_MINIMUM_QUERY_TIME", 40000, type_cast=int)
# How many hours backwards to look for queries to optimize
MATERIALIZE_COLUMNS_ANALYSIS_PERIOD_HOURS = get_from_env(
    "MATERIALIZE_COLUMNS_ANALYSIS_PERIOD_HOURS", 7 * 24, type_cast=int
)
# How big of a timeframe to backfill when materializing event properties. 0 for no backfilling
MATERIALIZE_COLUMNS_BACKFILL_PERIOD_DAYS = get_from_env("MATERIALIZE_COLUMNS_BACKFILL_PERIOD_DAYS", 0, type_cast=int)
# Maximum number of columns to materialize at once. Avoids running into resource bottlenecks (storage + ingest + backfilling).
MATERIALIZE_COLUMNS_MAX_AT_ONCE = get_from_env("MATERIALIZE_COLUMNS_MAX_AT_ONCE", 100, type_cast=int)

BILLING_SERVICE_URL = get_from_env("BILLING_SERVICE_URL", "https://billing.posthog.com")

# Whether to enable the admin portal. Default false for self-hosted as if not setup properly can pose security issues.
ADMIN_PORTAL_ENABLED = get_from_env("ADMIN_PORTAL_ENABLED", DEMO or DEBUG, type_cast=str_to_bool)

PARALLEL_ASSET_GENERATION_MAX_TIMEOUT_MINUTES = get_from_env(
    "PARALLEL_ASSET_GENERATION_MAX_TIMEOUT_MINUTES", 10.0, type_cast=float
)

HOOK_HOG_FUNCTION_TEAMS = get_from_env("HOOK_HOG_FUNCTION_TEAMS", "", type_cast=str)

# Assistant
ANTHROPIC_API_KEY = get_from_env("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = get_from_env("OPENAI_API_KEY", "")
INKEEP_API_KEY = get_from_env("INKEEP_API_KEY", "")
MISTRAL_API_KEY = get_from_env("MISTRAL_API_KEY", "")
GEMINI_API_KEY = get_from_env("GEMINI_API_KEY", "")

MAILJET_PUBLIC_KEY = get_from_env("MAILJET_PUBLIC_KEY", "", type_cast=str)
MAILJET_SECRET_KEY = get_from_env("MAILJET_SECRET_KEY", "", type_cast=str)

SQS_QUEUES = {
    "usage_reports": {
        "url": get_from_env("SQS_USAGE_REPORT_QUEUE_URL", optional=True),
        "region": get_from_env("SQS_REGION", "us-east-1", optional=True),
        "type": "usage_reports",
    },
    "billing": {
        "url": get_from_env("SQS_BILLING_QUEUE_URL", optional=True),
        "region": get_from_env("SQS_BILLING_REGION", "us-east-1", optional=True),
        "type": "billing",
    },
}

AZURE_INFERENCE_ENDPOINT = get_from_env("AZURE_INFERENCE_ENDPOINT", "", type_cast=str)
AZURE_INFERENCE_CREDENTIAL = get_from_env("AZURE_INFERENCE_CREDENTIAL", "", type_cast=str)
