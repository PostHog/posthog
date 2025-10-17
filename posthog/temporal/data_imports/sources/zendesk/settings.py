"""Zendesk source settings and constants"""

from dlt.common import pendulum

from posthog.warehouse.types import IncrementalField, IncrementalFieldType

DEFAULT_START_DATE = pendulum.datetime(year=2000, month=1, day=1)
PAGE_SIZE = 100
INCREMENTAL_PAGE_SIZE = 1000


CUSTOM_FIELDS_STATE_KEY = "ticket_custom_fields_v2"

# Resources that will always get pulled
BASE_ENDPOINTS = ["ticket_fields", "ticket_events", "tickets", "ticket_metric_events"]
INCREMENTAL_ENDPOINTS = ["tickets"]
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "tickets": [
        {
            "label": "generated_timestamp",
            "type": IncrementalFieldType.Integer,
            "field": "generated_timestamp",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
}

# Tuples of (Resource name, endpoint URL, data_key, supports pagination)
# data_key is the key which data list is nested under in responses
# if the data key is None it is assumed to be the same as the resource name
# The last element of the tuple says if endpoint supports cursor pagination
SUPPORT_ENDPOINTS = [
    ("users", "/api/v2/users.json", "users", True),
    ("sla_policies", "/api/v2/slas/policies.json", None, False),
    ("groups", "/api/v2/groups.json", None, True),
    ("organizations", "/api/v2/organizations.json", None, True),
    ("brands", "/api/v2/brands.json", None, True),
]

SUPPORT_EXTRA_ENDPOINTS = [
    ("activities", "/api/v2/activities.json", None, True),
    ("automations", "/api/v2/automations.json", None, True),
    ("custom_agent_roles", "/api/v2/custom_roles.json", "custom_roles", False),
    ("dynamic_content", "/api/v2/dynamic_content/items.json", "items", True),
    ("group_memberships", "/api/v2/group_memberships.json", None, True),
    ("job_status", "/api/v2/job_statuses.json", "job_statuses", True),
    ("macros", "/api/v2/macros.json", None, True),
    ("organization_fields", "/api/v2/organization_fields.json", None, True),
    ("organization_memberships", "/api/v2/organization_memberships.json", None, True),
    ("recipient_addresses", "/api/v2/recipient_addresses.json", None, True),
    ("requests", "/api/v2/requests.json", None, True),
    ("satisfaction_ratings", "/api/v2/satisfaction_ratings.json", None, True),
    ("sharing_agreements", "/api/v2/sharing_agreements.json", None, False),
    ("skips", "/api/v2/skips.json", None, True),
    ("suspended_tickets", "/api/v2/suspended_tickets.json", None, True),
    ("targets", "/api/v2/targets.json", None, False),
    ("ticket_forms", "/api/v2/ticket_forms.json", None, False),
    ("ticket_metrics", "/api/v2/ticket_metrics.json", None, True),
    ("triggers", "/api/v2/triggers.json", None, True),
    ("user_fields", "/api/v2/user_fields.json", None, True),
    ("views", "/api/v2/views.json", None, True),
    ("tags", "/api/v2/tags.json", None, True),
]

TALK_ENDPOINTS = [
    ("calls", "/api/v2/channels/voice/calls", None, False),
    ("addresses", "/api/v2/channels/voice/addresses", None, False),
    ("greeting_categories", "/api/v2/channels/voice/greeting_categories", None, False),
    ("greetings", "/api/v2/channels/voice/greetings", None, False),
    ("ivrs", "/api/v2/channels/voice/ivr", None, False),
    ("phone_numbers", "/api/v2/channels/voice/phone_numbers", None, False),
    ("settings", "/api/v2/channels/voice/settings", None, False),
    ("lines", "/api/v2/channels/voice/lines", None, False),
    ("agents_activity", "/api/v2/channels/voice/stats/agents_activity", None, False),
    (
        "current_queue_activity",
        "/api/v2/channels/voice/stats/current_queue_activity",
        None,
        False,
    ),
]

INCREMENTAL_TALK_ENDPOINTS = {
    "calls": "/api/v2/channels/voice/stats/incremental/calls.json",
    "legs": "/api/v2/channels/voice/stats/incremental/legs.json",
}
