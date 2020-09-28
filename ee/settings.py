"""
Django settings for PostHog Enterprise Edition.
"""
from posthog.settings import CLICKHOUSE, PRIMARY_DB, TEST

# Zapier
HOOK_EVENTS = {
    # "event_name": "App.Model.Action" (created/updated/deleted)
    "action_defined": "posthog.Action.created_custom",
    "action_performed": "posthog.Action.performed",
    "annotation_created": "posthog.Annotation.created_custom",
}
HOOK_FINDER = "ee.models.hook.find_and_fire_hook"
HOOK_DELIVERER = "ee.models.hook.deliver_hook_wrapper"

KAFKA_ENABLED = PRIMARY_DB == CLICKHOUSE and not TEST
