from dataclasses import dataclass
from typing import Literal

from posthog.temporal.data_imports.sources.common.rest_source.fanout import DependentEndpointConfig

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

DEFAULT_TYPEFORM_API_BASE_URL = "https://api.typeform.com"
ALLOWED_TYPEFORM_API_BASE_URLS = (
    DEFAULT_TYPEFORM_API_BASE_URL,
    "https://api.eu.typeform.com",
    "https://api.typeform.eu",
)

LAST_UPDATED_AT_INCREMENTAL: IncrementalField = {
    "label": "last_updated_at",
    "type": IncrementalFieldType.DateTime,
    "field": "last_updated_at",
    "field_type": IncrementalFieldType.DateTime,
}
SUBMITTED_AT_INCREMENTAL: IncrementalField = {
    "label": "submitted_at",
    "type": IncrementalFieldType.DateTime,
    "field": "submitted_at",
    "field_type": IncrementalFieldType.DateTime,
}


@dataclass
class TypeformEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    default_incremental_field: str | None = None
    partition_key: str | None = None
    page_size: int = 100
    sort_mode: Literal["asc", "desc"] = "asc"
    primary_key: str | list[str] = "id"
    fanout: DependentEndpointConfig | None = None


TYPEFORM_ENDPOINTS: dict[str, TypeformEndpointConfig] = {
    "forms": TypeformEndpointConfig(
        name="forms",
        path="/forms",
        incremental_fields=[LAST_UPDATED_AT_INCREMENTAL],
        default_incremental_field="last_updated_at",
        partition_key="created_at",
        primary_key="id",
        page_size=200,
        sort_mode="asc",
    ),
    "responses": TypeformEndpointConfig(
        name="responses",
        path="/forms/{form_id}/responses",
        incremental_fields=[SUBMITTED_AT_INCREMENTAL],
        default_incremental_field="submitted_at",
        partition_key="submitted_at",
        primary_key="token",
        page_size=1000,
        sort_mode="asc",
        fanout=DependentEndpointConfig(
            parent_name="forms",
            resolve_param="form_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "form_id"},
        ),
    ),
}

ENDPOINTS = tuple(TYPEFORM_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TYPEFORM_ENDPOINTS.items()
}
