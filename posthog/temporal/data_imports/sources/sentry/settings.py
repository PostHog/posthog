from dataclasses import dataclass
from typing import Literal, Optional

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class SentryEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    default_incremental_field: Optional[str] = None
    partition_key: Optional[str] = None
    page_size: int = 100
    sort_mode: Literal["asc", "desc"] = "asc"
    primary_key: str | list[str] = "id"
    is_project_fanout: bool = False
    is_issue_fanout: bool = False


SENTRY_ENDPOINTS: dict[str, SentryEndpointConfig] = {
    "projects": SentryEndpointConfig(
        name="projects",
        path="/organizations/{organization_slug}/projects/",
        incremental_fields=[],
    ),
    "teams": SentryEndpointConfig(
        name="teams",
        path="/organizations/{organization_slug}/teams/",
        incremental_fields=[],
        primary_key="id",
    ),
    "members": SentryEndpointConfig(
        name="members",
        path="/organizations/{organization_slug}/members/",
        incremental_fields=[],
        primary_key="id",
    ),
    "organization_users": SentryEndpointConfig(
        name="organization_users",
        path="/organizations/{organization_slug}/users/",
        incremental_fields=[],
        primary_key="id",
    ),
    "releases": SentryEndpointConfig(
        name="releases",
        path="/organizations/{organization_slug}/releases/",
        incremental_fields=[],
        primary_key="version",
    ),
    "environments": SentryEndpointConfig(
        name="environments",
        path="/organizations/{organization_slug}/environments/",
        incremental_fields=[],
        primary_key="id",
    ),
    "monitors": SentryEndpointConfig(
        name="monitors",
        path="/organizations/{organization_slug}/monitors/",
        incremental_fields=[],
        primary_key="id",
    ),
    "issues": SentryEndpointConfig(
        name="issues",
        path="/organizations/{organization_slug}/issues/",
        incremental_fields=[
            {
                "label": "lastSeen",
                "type": IncrementalFieldType.DateTime,
                "field": "lastSeen",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "firstSeen",
                "type": IncrementalFieldType.DateTime,
                "field": "firstSeen",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        default_incremental_field="lastSeen",
        partition_key="lastSeen",
        sort_mode="desc",
    ),
    "project_issues": SentryEndpointConfig(
        name="project_issues",
        path="/projects/{organization_slug}/{project_slug}/issues/",
        incremental_fields=[],
        primary_key=["project_id", "id"],
        is_project_fanout=True,
    ),
    "project_events": SentryEndpointConfig(
        name="project_events",
        path="/projects/{organization_slug}/{project_slug}/events/",
        incremental_fields=[],
        primary_key=["project_id", "eventID"],
        is_project_fanout=True,
    ),
    "project_users": SentryEndpointConfig(
        name="project_users",
        path="/projects/{organization_slug}/{project_slug}/users/",
        incremental_fields=[],
        primary_key=["project_id", "id"],
        is_project_fanout=True,
    ),
    "project_client_keys": SentryEndpointConfig(
        name="project_client_keys",
        path="/projects/{organization_slug}/{project_slug}/keys/",
        incremental_fields=[],
        primary_key=["project_id", "id"],
        is_project_fanout=True,
    ),
    "project_service_hooks": SentryEndpointConfig(
        name="project_service_hooks",
        path="/projects/{organization_slug}/{project_slug}/hooks/",
        incremental_fields=[],
        primary_key=["project_id", "id"],
        is_project_fanout=True,
    ),
    "issue_events": SentryEndpointConfig(
        name="issue_events",
        path="/issues/{issue_id}/events/",
        incremental_fields=[],
        primary_key=["issue_id", "eventID"],
        is_issue_fanout=True,
    ),
    "issue_hashes": SentryEndpointConfig(
        name="issue_hashes",
        path="/issues/{issue_id}/hashes/",
        incremental_fields=[],
        primary_key=["issue_id", "id"],
        is_issue_fanout=True,
    ),
    "issue_tag_values": SentryEndpointConfig(
        name="issue_tag_values",
        path="/issues/{issue_id}/tags/{tag_key}/values/",
        incremental_fields=[],
        primary_key=["issue_id", "tag_key", "value"],
        is_issue_fanout=True,
    ),
}

ENDPOINTS = tuple(SENTRY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SENTRY_ENDPOINTS.items()
}
