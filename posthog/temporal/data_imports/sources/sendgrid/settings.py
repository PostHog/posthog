from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = (
    "campaigns",
    "lists",
    "contacts",
    "segments",
    "singlesends",
    "templates",
    "global_suppressions",
    "suppression_groups",
    "suppression_group_members",
    "blocks",
    "bounces",
    "invalid_emails",
    "spam_reports",
)

INCREMENTAL_ENDPOINTS = (
    "global_suppressions",
    "suppression_group_members",
    "blocks",
    "bounces",
    "invalid_emails",
    "spam_reports",
)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "global_suppressions": [
        {
            "label": "created",
            "type": IncrementalFieldType.Integer,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
    "suppression_group_members": [
        {
            "label": "created_at",
            "type": IncrementalFieldType.Integer,
            "field": "created_at",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
    "blocks": [
        {
            "label": "created",
            "type": IncrementalFieldType.Integer,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
    "bounces": [
        {
            "label": "created",
            "type": IncrementalFieldType.Integer,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
    "invalid_emails": [
        {
            "label": "created",
            "type": IncrementalFieldType.Integer,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
    "spam_reports": [
        {
            "label": "created",
            "type": IncrementalFieldType.Integer,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
}
