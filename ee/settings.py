"""
Django settings for PostHog Enterprise Edition.
"""
import os
from typing import Dict, List

from posthog.constants import AnalyticsDBMS
from posthog.settings import AUTHENTICATION_BACKENDS, PRIMARY_DB, SITE_URL, TEST, get_from_env
from posthog.utils import str_to_bool

# Zapier REST hooks
HOOK_EVENTS: Dict[str, str] = {
    # "event_name": "App.Model.Action" (created/updated/deleted)
    "action_defined": "posthog.Action.created_custom",
    "action_performed": "posthog.Action.performed",
    "annotation_created": "posthog.Annotation.created_custom",
}
HOOK_FINDER = "ee.models.hook.find_and_fire_hook"
HOOK_DELIVERER = "ee.models.hook.deliver_hook_wrapper"

# Social auth
SOCIAL_AUTH_GOOGLE_OAUTH2_KEY = os.getenv("SOCIAL_AUTH_GOOGLE_OAUTH2_KEY")
SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET = os.getenv("SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET")
if "SOCIAL_AUTH_GOOGLE_OAUTH2_WHITELISTED_DOMAINS" in os.environ:
    SOCIAL_AUTH_GOOGLE_OAUTH2_WHITELISTED_DOMAINS: List[str] = os.environ[
        "SOCIAL_AUTH_GOOGLE_OAUTH2_WHITELISTED_DOMAINS"
    ].split(",")

AUTHENTICATION_BACKENDS = AUTHENTICATION_BACKENDS + [
    "social_core.backends.google.GoogleOAuth2",
]

# SAML
SAML_DISABLED = get_from_env("SAML_DISABLED", False, type_cast=str_to_bool)
SAML_CONFIGURED = False
SOCIAL_AUTH_SAML_SP_ENTITY_ID = SITE_URL
SOCIAL_AUTH_SAML_SECURITY_CONFIG = {
    "wantAttributeStatement": False,  # AttributeStatement is optional in the specification
}
# Attributes below are required for the SAML integration from social_core to work properly
SOCIAL_AUTH_SAML_SP_PUBLIC_CERT = ""
SOCIAL_AUTH_SAML_SP_PRIVATE_KEY = ""
SOCIAL_AUTH_SAML_ORG_INFO = {"en-US": {"name": "posthog", "displayname": "PostHog", "url": "https://posthog.com"}}
SOCIAL_AUTH_SAML_TECHNICAL_CONTACT = {"givenName": "PostHog Support", "emailAddress": "hey@posthog.com"}
SOCIAL_AUTH_SAML_SUPPORT_CONTACT = SOCIAL_AUTH_SAML_TECHNICAL_CONTACT

# Set settings only if SAML is enabled
if not SAML_DISABLED and os.getenv("SAML_ENTITY_ID") and os.getenv("SAML_ACS_URL") and os.getenv("SAML_X509_CERT"):
    SAML_CONFIGURED = True
    AUTHENTICATION_BACKENDS = AUTHENTICATION_BACKENDS + [
        "social_core.backends.saml.SAMLAuth",
    ]
    SOCIAL_AUTH_SAML_ENABLED_IDPS = {
        "posthog_custom": {
            "entity_id": os.getenv("SAML_ENTITY_ID"),
            "url": os.getenv("SAML_ACS_URL"),
            "x509cert": os.getenv("SAML_X509_CERT"),
            "attr_user_permanent_id": os.getenv("SAML_ATTR_PERMANENT_ID", "name_id"),
            "attr_first_name": os.getenv("SAML_ATTR_FIRST_NAME", "first_name"),
            "attr_last_name": os.getenv("SAML_ATTR_LAST_NAME", "last_name"),
            "attr_email": os.getenv("SAML_ATTR_EMAIL", "email"),
        },
    }
    SAML_ENFORCED = get_from_env("SAML_ENFORCED", False, type_cast=str_to_bool)


# ClickHouse and Kafka
KAFKA_ENABLED = PRIMARY_DB == AnalyticsDBMS.CLICKHOUSE and not TEST

# Settings specific for materialized columns

# Whether materialized columns should be created or used at query time
MATERIALIZED_COLUMNS_ENABLED = get_from_env("MATERIALIZED_COLUMNS_ENABLED", True, type_cast=str_to_bool)

# Schedule to run column materialization on. Follows crontab syntax.
# Use empty string to prevent from materializing
MATERIALIZE_COLUMNS_SCHEDULE_CRON = get_from_env("MATERIALIZE_COLUMNS_SCHEDULE_CRON", "0 5 * * SAT")
# Minimum query time before a query if considered for optimization by adding materialized columns
MATERIALIZE_COLUMNS_MINIMUM_QUERY_TIME = get_from_env("MATERIALIZE_COLUMNS_MINIMUM_QUERY_TIME", 3000, type_cast=int)
# How many hours backwards to look for queries to optimize
MATERIALIZE_COLUMNS_ANALYSIS_PERIOD_HOURS = get_from_env(
    "MATERIALIZE_COLUMNS_ANALYSIS_PERIOD_HOURS", 7 * 24, type_cast=int
)
# How big of a timeframe to backfill when materializing event properties. 0 for no backfilling
MATERIALIZE_COLUMNS_BACKFILL_PERIOD_DAYS = get_from_env("MATERIALIZE_COLUMNS_BACKFILL_PERIOD_DAYS", 90, type_cast=int)
# Maximum number of columns to materialize at once. Avoids running into resource bottlenecks (storage + ingest + backfilling).
MATERIALIZE_COLUMNS_MAX_AT_ONCE = get_from_env("MATERIALIZE_COLUMNS_MAX_AT_ONCE", 10, type_cast=int)
