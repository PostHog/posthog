from dataclasses import dataclass
from typing import Optional

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class GithubEndpointConfig:
    name: str
    path: str  # Path template with {repository} placeholder
    incremental_fields: list[IncrementalField]
    default_incremental_field: Optional[str] = None
    partition_key: Optional[str] = None
    page_size: int = 100  # GitHub default, max is 100


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
        incremental_fields=[],  # GitHub pulls API doesn't support 'since' parameter
    ),
    "commits": GithubEndpointConfig(
        name="commits",
        path="/repos/{repository}/commits",
        partition_key="created_at",
        incremental_fields=[],  # Commits use 'since' param but response has nested author.date
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
}

ENDPOINTS = tuple(GITHUB_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GITHUB_ENDPOINTS.items()
}
