"""Mailgun source settings and constants"""

# Mailgun API endpoints
# Full list of the Mailgun API endpoints: https://documentation.mailgun.com/docs/mailgun/api-reference/

EVENTS_ENDPOINT = "events"
DOMAINS_ENDPOINT = "domains"
BOUNCES_ENDPOINT = "bounces"
COMPLAINTS_ENDPOINT = "complaints"
UNSUBSCRIBES_ENDPOINT = "unsubscribes"

ENDPOINTS = (
    EVENTS_ENDPOINT,
    DOMAINS_ENDPOINT,
    BOUNCES_ENDPOINT,
    COMPLAINTS_ENDPOINT,
    UNSUBSCRIBES_ENDPOINT,
)

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    EVENTS_ENDPOINT: [
        {
            "label": "timestamp",
            "type": IncrementalFieldType.DateTime,
            "field": "timestamp",
            "field_type": IncrementalFieldType.Numeric,
        }
    ],
    BOUNCES_ENDPOINT: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    COMPLAINTS_ENDPOINT: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    UNSUBSCRIBES_ENDPOINT: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}
