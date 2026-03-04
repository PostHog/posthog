import re
from datetime import date, datetime
from typing import Any, Optional

import requests
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator

from posthog.security.outbound_proxy import external_requests
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from posthog.temporal.data_imports.sources.sentry.settings import SENTRY_ENDPOINTS


def _normalize_api_base_url(api_base_url: str | None) -> str:
    return (api_base_url or "https://sentry.io").rstrip("/")


def _format_incremental_value(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).isoformat()
    return str(value)


class SentryPaginator(BasePaginator):
    """Paginator for Sentry API Link-header cursor pagination."""

    def __init__(self) -> None:
        super().__init__()
        self._next_url: str | None = None

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        link_header = response.headers.get("Link", "")

        self._next_url = None
        self._has_next_page = False

        if not link_header:
            return

        for part in link_header.split(","):
            part = part.strip()
            next_match = re.search(r'<([^>]+)>;\s*rel="next"', part)
            if not next_match:
                continue

            results_match = re.search(r'results="(true|false)"', part)
            has_results = results_match and results_match.group(1) == "true"
            if has_results:
                self._next_url = next_match.group(1)
                self._has_next_page = True
            break

    def update_request(self, request: Request) -> None:
        if self._next_url:
            request.url = self._next_url
            request.params = {}


def validate_credentials(
    auth_token: str,
    organization_slug: str,
    api_base_url: str | None = None,
) -> tuple[bool, str | None]:
    base_url = _normalize_api_base_url(api_base_url)
    url = f"{base_url}/api/0/organizations/{organization_slug}/projects/"
    headers = {"Authorization": f"Bearer {auth_token}", "Accept": "application/json"}

    try:
        response = external_requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return True, None
        if response.status_code == 401:
            return False, "Invalid Sentry auth token"
        if response.status_code == 403:
            return False, "Sentry token is missing required scopes (org:read)"
        if response.status_code == 404:
            return False, f"Sentry organization '{organization_slug}' not found"

        try:
            return False, response.json().get("detail", response.text)
        except Exception:
            return False, response.text
    except requests.exceptions.RequestException as exc:
        return False, str(exc)


def get_resource(
    endpoint: str,
    organization_slug: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> EndpointResource:
    config = SENTRY_ENDPOINTS[endpoint]
    params: dict[str, Any] = {"limit": config.page_size}

    if endpoint == "issues":
        params["query"] = ""
        params["sort"] = "date" if (incremental_field or config.default_incremental_field) == "lastSeen" else "new"
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            params["start"] = _format_incremental_value(db_incremental_field_last_value)

    return {
        "name": config.name,
        "table_name": config.name,
        "primary_key": config.primary_key,
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field and bool(config.incremental_fields)
        else "replace",
        "endpoint": {
            "path": config.path.format(organization_slug=organization_slug),
            "params": params,
        },
        "table_format": "delta",
    }


def sentry_source(
    auth_token: str,
    organization_slug: str,
    api_base_url: str | None,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = SENTRY_ENDPOINTS[endpoint]

    config: RESTAPIConfig = {
        "client": {
            "base_url": f"{_normalize_api_base_url(api_base_url)}/api/0",
            "auth": {"type": "bearer", "token": auth_token},
            "headers": {"Accept": "application/json"},
            "paginator": SentryPaginator(),
        },
        "resource_defaults": {
            "primary_key": endpoint_config.primary_key,
            "write_disposition": "replace",
            "endpoint": {"params": {"limit": endpoint_config.page_size}},
        },
        "resources": [
            get_resource(
                endpoint=endpoint,
                organization_slug=organization_slug,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
                incremental_field=incremental_field,
            )
        ],
    }

    resources = rest_api_resources(config, team_id, job_id, db_incremental_field_last_value)
    assert len(resources) == 1
    resource = resources[0]

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[endpoint_config.primary_key],
        sort_mode=endpoint_config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
