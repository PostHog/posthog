"""
Django settings for PostHog Enterprise Edition.
"""
import os
from typing import Dict, List

from posthog.constants import RDBMS
from posthog.settings import AUTHENTICATION_BACKENDS, PRIMARY_DB, TEST, get_from_env

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

# ClickHouse and Kafka
KAFKA_ENABLED = PRIMARY_DB == RDBMS.CLICKHOUSE and not TEST

# Settings specific for materialized columns
# Minimum query time before a query if considered for optimization by adding materialized columns
MATERIALIZED_COLUMNS_MINIMUM_QUERY_TIME = get_from_env("MATERIALIZED_COLUMNS_MINIMUM_QUERY_TIME", 3000, type_cast=int)
