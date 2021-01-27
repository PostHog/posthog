"""
Django settings for PostHog Enterprise Edition.
"""
import os
from typing import Dict, List

from posthog.constants import RDBMS
from posthog.settings import PRIMARY_DB, TEST

# Zapier
HOOK_EVENTS: Dict[str, str] = {
    # "event_name": "App.Model.Action" (created/updated/deleted)
    "action_defined": "posthog.Action.created_custom",
    "action_performed": "posthog.Action.performed",
    "annotation_created": "posthog.Annotation.created_custom",
}
HOOK_FINDER = "ee.models.hook.find_and_fire_hook"
HOOK_DELIVERER = "ee.models.hook.deliver_hook_wrapper"

KAFKA_ENABLED = PRIMARY_DB == RDBMS.CLICKHOUSE and not TEST

SOCIAL_AUTH_GOOGLE_OAUTH2_KEY = os.environ.get("SOCIAL_AUTH_GOOGLE_OAUTH2_KEY")
SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET = os.environ.get("SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET")
SOCIAL_AUTH_GOOGLE_OAUTH2_WHITELISTED_DOMAINS: List[str] = os.environ.get(
    "SOCIAL_AUTH_GOOGLE_OAUTH2_WHITELISTED_DOMAINS", ""
).split(",")

PLUGINS_CLOUD_WHITELISTED_ORG_IDS: List[str] = os.getenv("PLUGINS_CLOUD_WHITELISTED_ORG_IDS", "").split(",")

CLICKHOUSE_DENORMALIZED_PROPERTIES = os.environ.get("CLICKHOUSE_DENORMALIZED_PROPERTIES", "").split(",")
