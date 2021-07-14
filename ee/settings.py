"""
Django settings for PostHog Enterprise Edition.
"""
import os
from typing import Dict, List

from posthog.constants import RDBMS
from posthog.settings import PRIMARY_DB, TEST

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

# ClickHouse and Kafka
CLICKHOUSE_DENORMALIZED_PROPERTIES: list = (
    os.getenv("CLICKHOUSE_DENORMALIZED_PROPERTIES", "").split(",")
    if os.getenv("CLICKHOUSE_DENORMALIZED_PROPERTIES")
    else []
)
KAFKA_ENABLED = PRIMARY_DB == RDBMS.CLICKHOUSE and not TEST
