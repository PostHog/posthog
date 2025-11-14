from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

# Jira API endpoints supported by this source
ENDPOINTS = [
    "issues",
    "projects",
    "users",
    "issue_comments",
    "boards",
    "sprints",
    "components",
    "worklogs",
]

# Incremental fields for each endpoint
# These are fields that can be used for incremental sync
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "issues": [
        {
            "label": "Updated",
            "type": IncrementalFieldType.DateTime,
            "field": "updated",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "issue_comments": [
        {
            "label": "Updated",
            "type": IncrementalFieldType.DateTime,
            "field": "updated",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "worklogs": [
        {
            "label": "Updated",
            "type": IncrementalFieldType.DateTime,
            "field": "updated",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}
