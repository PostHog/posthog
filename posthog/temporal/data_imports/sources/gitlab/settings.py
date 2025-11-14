"""GitLab analytics source settings and constants"""

from posthog.temporal.data_imports.sources.gitlab.constants import (
    BRANCH_RESOURCE_NAME,
    COMMIT_RESOURCE_NAME,
    GROUP_RESOURCE_NAME,
    ISSUE_RESOURCE_NAME,
    JOB_RESOURCE_NAME,
    MERGE_REQUEST_RESOURCE_NAME,
    MILESTONE_RESOURCE_NAME,
    PIPELINE_RESOURCE_NAME,
    PROJECT_RESOURCE_NAME,
    RELEASE_RESOURCE_NAME,
    TAG_RESOURCE_NAME,
    USER_RESOURCE_NAME,
)
from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

# The most popular GitLab API endpoints for analytics
# Full list of GitLab API endpoints: https://docs.gitlab.com/api/api_resources/
ENDPOINTS = (
    PROJECT_RESOURCE_NAME,
    ISSUE_RESOURCE_NAME,
    MERGE_REQUEST_RESOURCE_NAME,
    PIPELINE_RESOURCE_NAME,
    JOB_RESOURCE_NAME,
    COMMIT_RESOURCE_NAME,
    BRANCH_RESOURCE_NAME,
    TAG_RESOURCE_NAME,
    RELEASE_RESOURCE_NAME,
    MILESTONE_RESOURCE_NAME,
    USER_RESOURCE_NAME,
    GROUP_RESOURCE_NAME,
)

# Incremental field configurations for each endpoint
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    PROJECT_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        },
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "last_activity_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    ISSUE_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        },
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    MERGE_REQUEST_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        },
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    PIPELINE_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        },
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    JOB_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    COMMIT_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    RELEASE_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    MILESTONE_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        },
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    USER_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
}
