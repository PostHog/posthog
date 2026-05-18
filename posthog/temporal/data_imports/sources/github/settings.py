from dataclasses import dataclass
from typing import Literal, Optional

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class GithubEndpointConfig:
    name: str
    path: str  # Path template with {repository} placeholder
    incremental_fields: list[IncrementalField]
    default_incremental_field: Optional[str] = None
    partition_key: Optional[str] = None
    page_size: int = 100  # GitHub default, max is 100
    sort_mode: Literal["asc", "desc"] = "asc"
    primary_key: str = "id"  # Primary key for upsert operations
    # Body key to drill into when the API wraps results in an envelope
    # (e.g. /actions/runs returns {"total_count": N, "workflow_runs": [...]}).
    # None means the response body is itself the list.
    response_data_path: Optional[str] = None


GITHUB_ENDPOINTS: dict[str, GithubEndpointConfig] = {
    "issues": GithubEndpointConfig(
        name="issues",
        path="/repos/{repository}/issues",
        partition_key="created_at",
        incremental_fields=[
            {
                "label": "updated_at",
                "type": IncrementalFieldType.DateTime,
                "field": "updated_at",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        default_incremental_field="updated_at",
    ),
    "pull_requests": GithubEndpointConfig(
        name="pull_requests",
        path="/repos/{repository}/pulls",
        partition_key="created_at",
        incremental_fields=[
            {
                "label": "updated_at",
                "type": IncrementalFieldType.DateTime,
                "field": "updated_at",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        default_incremental_field="updated_at",
        sort_mode="desc",  # Use descending sort to enable incremental sync
    ),
    "commits": GithubEndpointConfig(
        name="commits",
        path="/repos/{repository}/commits",
        partition_key="created_at",
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",  # Flattened from commit.author.date
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        default_incremental_field="created_at",
        primary_key="sha",  # Commits use sha as unique identifier
        sort_mode="desc",  # GitHub commits API always returns newest-first, ignores sort/direction params
    ),
    "stargazers": GithubEndpointConfig(
        name="stargazers",
        path="/repos/{repository}/stargazers",
        partition_key="starred_at",
        incremental_fields=[],  # No incremental support
    ),
    "releases": GithubEndpointConfig(
        name="releases",
        path="/repos/{repository}/releases",
        partition_key="created_at",
        incremental_fields=[],  # No incremental support
    ),
    "workflow_runs": GithubEndpointConfig(
        name="workflow_runs",
        path="/repos/{repository}/actions/runs",
        partition_key="created_at",
        incremental_fields=[
            # GitHub's workflow_runs API only filters by `created` server-side
            # and returns newest-first by created_at. updated_at is not
            # filterable or sortable, so we don't expose it as a cursor.
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        default_incremental_field="created_at",
        sort_mode="desc",  # Workflow runs API always returns newest-first
        response_data_path="workflow_runs",
    ),
}

ENDPOINTS = tuple(GITHUB_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GITHUB_ENDPOINTS.items()
}
