"""GitHub source settings and constants"""

from posthog.temporal.data_imports.sources.github.constants import (
    BRANCHES_RESOURCE_NAME,
    COLLABORATORS_RESOURCE_NAME,
    COMMITS_RESOURCE_NAME,
    EVENTS_RESOURCE_NAME,
    ISSUE_COMMENTS_RESOURCE_NAME,
    ISSUES_RESOURCE_NAME,
    PULL_REQUEST_COMMENTS_RESOURCE_NAME,
    PULL_REQUESTS_RESOURCE_NAME,
    RELEASES_RESOURCE_NAME,
    REVIEWS_RESOURCE_NAME,
    STARGAZERS_RESOURCE_NAME,
    TAGS_RESOURCE_NAME,
    WORKFLOW_RUNS_RESOURCE_NAME,
    WORKFLOWS_RESOURCE_NAME,
)

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

# All available endpoints
ENDPOINTS = (
    ISSUES_RESOURCE_NAME,
    PULL_REQUESTS_RESOURCE_NAME,
    COMMITS_RESOURCE_NAME,
    ISSUE_COMMENTS_RESOURCE_NAME,
    PULL_REQUEST_COMMENTS_RESOURCE_NAME,
    REVIEWS_RESOURCE_NAME,
    RELEASES_RESOURCE_NAME,
    STARGAZERS_RESOURCE_NAME,
    EVENTS_RESOURCE_NAME,
    WORKFLOWS_RESOURCE_NAME,
    WORKFLOW_RUNS_RESOURCE_NAME,
    BRANCHES_RESOURCE_NAME,
    TAGS_RESOURCE_NAME,
    COLLABORATORS_RESOURCE_NAME,
)

# Incremental fields mapping for each endpoint
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    ISSUES_RESOURCE_NAME: [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    PULL_REQUESTS_RESOURCE_NAME: [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    COMMITS_RESOURCE_NAME: [
        {
            "label": "committed_date",
            "type": IncrementalFieldType.DateTime,
            "field": "commit.author.date",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    ISSUE_COMMENTS_RESOURCE_NAME: [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    PULL_REQUEST_COMMENTS_RESOURCE_NAME: [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    REVIEWS_RESOURCE_NAME: [
        {
            "label": "submitted_at",
            "type": IncrementalFieldType.DateTime,
            "field": "submitted_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    RELEASES_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    STARGAZERS_RESOURCE_NAME: [
        {
            "label": "starred_at",
            "type": IncrementalFieldType.DateTime,
            "field": "starred_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    EVENTS_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    WORKFLOW_RUNS_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}
