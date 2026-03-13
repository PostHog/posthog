from dataclasses import dataclass
from typing import Literal

from posthog.temporal.data_imports.sources.common.rest_source.fanout import DependentEndpointConfig

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

DEFAULT_SENTRY_API_BASE_URL = "https://sentry.io"
ALLOWED_SENTRY_API_BASE_URLS = (
    DEFAULT_SENTRY_API_BASE_URL,
    "https://us.sentry.io",
    "https://de.sentry.io",
)

LAST_SEEN_INCREMENTAL: IncrementalField = {
    "label": "lastSeen",
    "type": IncrementalFieldType.DateTime,
    "field": "lastSeen",
    "field_type": IncrementalFieldType.DateTime,
}
FIRST_SEEN_INCREMENTAL: IncrementalField = {
    "label": "firstSeen",
    "type": IncrementalFieldType.DateTime,
    "field": "firstSeen",
    "field_type": IncrementalFieldType.DateTime,
}
DATE_CREATED_INCREMENTAL: IncrementalField = {
    "label": "dateCreated",
    "type": IncrementalFieldType.DateTime,
    "field": "dateCreated",
    "field_type": IncrementalFieldType.DateTime,
}

ISSUES_INCREMENTAL_FIELDS: list[IncrementalField] = [LAST_SEEN_INCREMENTAL, FIRST_SEEN_INCREMENTAL]
DATE_CREATED_INCREMENTAL_FIELD: list[IncrementalField] = [
    DATE_CREATED_INCREMENTAL,
]
LAST_SEEN_INCREMENTAL_FIELD: list[IncrementalField] = [
    LAST_SEEN_INCREMENTAL,
]


@dataclass
class SentryEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    default_incremental_field: str | None = None
    partition_key: str | None = None
    page_size: int = 100
    sort_mode: Literal["asc", "desc"] = "asc"
    primary_key: str | list[str] = "id"
    fanout: DependentEndpointConfig | None = None


SENTRY_ENDPOINTS: dict[str, SentryEndpointConfig] = {
    "projects": SentryEndpointConfig(
        name="projects",
        path="/organizations/{organization_slug}/projects/",
        incremental_fields=[],
        partition_key="date_created",
    ),
    "teams": SentryEndpointConfig(
        name="teams",
        path="/organizations/{organization_slug}/teams/",
        incremental_fields=[],
        partition_key="date_created",
        primary_key="id",
    ),
    "members": SentryEndpointConfig(
        name="members",
        path="/organizations/{organization_slug}/members/",
        incremental_fields=[],
        partition_key="date_created",
        primary_key="id",
    ),
    "releases": SentryEndpointConfig(
        name="releases",
        path="/organizations/{organization_slug}/releases/",
        incremental_fields=[],
        partition_key="date_created",
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
        partition_key="date_created",
        primary_key="id",
    ),
    "issues": SentryEndpointConfig(
        name="issues",
        path="/organizations/{organization_slug}/issues/",
        incremental_fields=ISSUES_INCREMENTAL_FIELDS,
        default_incremental_field="lastSeen",
        partition_key="first_seen",
        sort_mode="desc",
    ),
    "project_events": SentryEndpointConfig(
        name="project_events",
        path="/projects/{organization_slug}/{project_slug}/events/",
        incremental_fields=DATE_CREATED_INCREMENTAL_FIELD,
        default_incremental_field="dateCreated",
        partition_key="date_created",
        primary_key=["project_id", "event_id"],
        fanout=DependentEndpointConfig(
            parent_name="projects",
            resolve_param="project_slug",
            resolve_field="slug",
            include_from_parent=["id", "slug"],
            parent_field_renames={"id": "project_id", "slug": "project_slug"},
        ),
    ),
    "project_users": SentryEndpointConfig(
        name="project_users",
        path="/projects/{organization_slug}/{project_slug}/users/",
        incremental_fields=[],
        primary_key=["project_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="projects",
            resolve_param="project_slug",
            resolve_field="slug",
            include_from_parent=["id", "slug"],
            parent_field_renames={"id": "project_id", "slug": "project_slug"},
        ),
    ),
    "project_client_keys": SentryEndpointConfig(
        name="project_client_keys",
        path="/projects/{organization_slug}/{project_slug}/keys/",
        incremental_fields=[],
        partition_key="date_created",
        primary_key=["project_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="projects",
            resolve_param="project_slug",
            resolve_field="slug",
            include_from_parent=["id", "slug"],
            parent_field_renames={"id": "project_id", "slug": "project_slug"},
        ),
    ),
    "project_service_hooks": SentryEndpointConfig(
        name="project_service_hooks",
        path="/projects/{organization_slug}/{project_slug}/hooks/",
        incremental_fields=[],
        partition_key="date_created",
        primary_key=["project_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="projects",
            resolve_param="project_slug",
            resolve_field="slug",
            include_from_parent=["id", "slug"],
            parent_field_renames={"id": "project_id", "slug": "project_slug"},
        ),
    ),
    "issue_events": SentryEndpointConfig(
        name="issue_events",
        path="/organizations/{organization_slug}/issues/{issue_id}/events/",
        incremental_fields=DATE_CREATED_INCREMENTAL_FIELD,
        default_incremental_field="dateCreated",
        partition_key="date_created",
        primary_key=["issue_id", "event_id"],
        fanout=DependentEndpointConfig(
            parent_name="issues",
            resolve_param="issue_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "issue_id"},
            parent_params={"query": "", "sort": "date"},
        ),
    ),
    "issue_hashes": SentryEndpointConfig(
        name="issue_hashes",
        path="/organizations/{organization_slug}/issues/{issue_id}/hashes/",
        incremental_fields=[],
        primary_key=["issue_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="issues",
            resolve_param="issue_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "issue_id"},
            parent_params={"query": "", "sort": "date"},
        ),
    ),
    "issue_tag_values": SentryEndpointConfig(
        name="issue_tag_values",
        path="/organizations/{organization_slug}/issues/{issue_id}/tags/{tag_key}/values/",
        incremental_fields=LAST_SEEN_INCREMENTAL_FIELD,
        default_incremental_field="lastSeen",
        partition_key="first_seen",
        sort_mode="desc",
        primary_key=["issue_id", "tag_key", "value"],
    ),
}

ENDPOINTS = tuple(SENTRY_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SENTRY_ENDPOINTS.items()
}
