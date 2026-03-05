import re
import time
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import quote, urljoin

import requests
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator

from posthog.security.outbound_proxy import external_requests
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from posthog.temporal.data_imports.sources.sentry.settings import SENTRY_ENDPOINTS, SentryEndpointConfig

_MAX_PROJECTS = 200
_MAX_PAGES_PER_PARENT = 10
_REQUEST_TIMEOUT = 30
_MAX_RETRIES = 3


def _normalize_api_base_url(api_base_url: str | None) -> str:
    return (api_base_url or "https://sentry.io").rstrip("/")


def _format_incremental_value(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).isoformat()
    return str(value)


def _parse_next_link(link_header: str) -> str | None:
    if not link_header:
        return None

    for part in link_header.split(","):
        part = part.strip()
        next_match = re.search(r'<([^>]+)>;\s*rel="next"', part)
        if not next_match:
            continue
        results_match = re.search(r'results="(true|false)"', part)
        if results_match and results_match.group(1) == "true":
            return next_match.group(1)
        return None
    return None


class SentryPaginator(BasePaginator):
    """Paginator for Sentry API Link-header cursor pagination."""

    def __init__(self) -> None:
        super().__init__()
        self._next_url: str | None = None

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        link_header = response.headers.get("Link", "")
        self._next_url = _parse_next_link(link_header)
        self._has_next_page = self._next_url is not None

    def update_request(self, request: Request) -> None:
        if self._next_url:
            request.url = self._next_url
            request.params = {}


# ---------------------------------------------------------------------------
# Low-level HTTP helpers (used by project fan-out and issue_tag_values only)
# ---------------------------------------------------------------------------


def _request_with_retry(
    url: str,
    headers: dict[str, str],
    params: dict[str, Any] | None,
    timeout: int = _REQUEST_TIMEOUT,
    max_retries: int = _MAX_RETRIES,
) -> requests.Response:
    last_response: requests.Response | None = None
    last_exception: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            response = external_requests.get(url, headers=headers, params=params, timeout=timeout)
            last_response = response
            if response.status_code not in (429, 500, 502, 503, 504):
                return response
            if attempt == max_retries:
                return response
        except requests.exceptions.RequestException as exc:
            last_exception = exc
            if attempt == max_retries:
                raise

        backoff = min(2**attempt, 30)
        time.sleep(backoff)

    if last_response is not None:
        return last_response
    if last_exception is not None:
        raise last_exception
    raise RuntimeError("Unexpected request retry state")


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        return [payload]
    return []


def _iter_endpoint_rows(
    base_api_url: str,
    path: str,
    headers: dict[str, str],
    params: dict[str, Any] | None,
    max_pages: int | None = None,
) -> Iterator[dict[str, Any]]:
    url = urljoin(f"{base_api_url}/", path.lstrip("/"))
    current_params = params or {}
    pages_read = 0
    max_pages_to_read = max_pages if max_pages and max_pages > 0 else None

    while url:
        if max_pages_to_read is not None and pages_read >= max_pages_to_read:
            break

        response = _request_with_retry(url=url, headers=headers, params=current_params)
        response.raise_for_status()

        payload = response.json()
        yield from _extract_rows(payload)

        pages_read += 1
        next_url = _parse_next_link(response.headers.get("Link", ""))
        if not next_url:
            break
        url = urljoin(f"{base_api_url}/", next_url)
        current_params = None


# ---------------------------------------------------------------------------
# Project fan-out (custom iterator — projects don't have a stable parent id
# we can resolve declaratively)
# ---------------------------------------------------------------------------


def _iter_project_fanout_rows(
    base_api_url: str,
    headers: dict[str, str],
    organization_slug: str,
    endpoint: str,
) -> Iterator[dict[str, Any]]:
    endpoint_config = SENTRY_ENDPOINTS[endpoint]
    projects = _iter_endpoint_rows(
        base_api_url=base_api_url,
        path=f"/organizations/{organization_slug}/projects/",
        headers=headers,
        params={"limit": 100},
    )

    for index, project in enumerate(projects):
        if index >= _MAX_PROJECTS:
            break

        project_slug = project.get("slug")
        project_id = project.get("id")
        if not project_slug:
            continue

        path = endpoint_config.path.format(organization_slug=organization_slug, project_slug=project_slug)

        for row in _iter_endpoint_rows(
            base_api_url=base_api_url,
            path=path,
            headers=headers,
            params={"limit": endpoint_config.page_size},
            max_pages=_MAX_PAGES_PER_PARENT,
        ):
            row["project_slug"] = project_slug
            row["project_id"] = project_id
            yield row


# ---------------------------------------------------------------------------
# Issue tag-values fan-out (custom iterator — requires tag-key discovery per
# issue, which can't be expressed as a single rest_api_resources dependency)
# ---------------------------------------------------------------------------


def _iter_issue_tag_values_rows(
    base_api_url: str,
    headers: dict[str, str],
    organization_slug: str,
) -> Iterator[dict[str, Any]]:
    issues = _iter_endpoint_rows(
        base_api_url=base_api_url,
        path=f"/organizations/{organization_slug}/issues/",
        headers=headers,
        params={"limit": 100, "query": "", "sort": "date"},
    )

    for issue in issues:
        issue_id = str(issue.get("id", ""))
        if not issue_id:
            continue

        tags = list(
            _iter_endpoint_rows(
                base_api_url=base_api_url,
                path=f"/organizations/{organization_slug}/issues/{issue_id}/tags/",
                headers=headers,
                params={"limit": 100},
                max_pages=_MAX_PAGES_PER_PARENT,
            )
        )

        for tag in tags:
            tag_key = tag.get("key") or tag.get("id")
            if not isinstance(tag_key, str) or not tag_key:
                continue

            values_path = f"/organizations/{organization_slug}/issues/{issue_id}/tags/{quote(tag_key, safe='')}/values/"
            for row in _iter_endpoint_rows(
                base_api_url=base_api_url,
                path=values_path,
                headers=headers,
                params={"limit": 100},
                max_pages=_MAX_PAGES_PER_PARENT,
            ):
                row["issue_id"] = issue_id
                row["tag_key"] = tag_key
                yield row


# ---------------------------------------------------------------------------
# Credential validation
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Resource config builder (org-level flat endpoints only)
# ---------------------------------------------------------------------------


def get_resource(
    endpoint: str,
    organization_slug: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> EndpointResource:
    config = SENTRY_ENDPOINTS[endpoint]
    if config.is_project_fanout or config.is_issue_fanout:
        raise ValueError(f"Fan-out endpoint '{endpoint}' must use the fan-out path")

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


# ---------------------------------------------------------------------------
# Shared helper to reduce SourceResponse boilerplate
# ---------------------------------------------------------------------------


def _make_source_response(endpoint_config: SentryEndpointConfig, items_fn) -> SourceResponse:
    return SourceResponse(
        name=endpoint_config.name,
        items=items_fn,
        primary_keys=endpoint_config.primary_key
        if isinstance(endpoint_config.primary_key, list)
        else [endpoint_config.primary_key],
        sort_mode=endpoint_config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


# ---------------------------------------------------------------------------
# Main entry point — routes each endpoint to the right extraction strategy
# ---------------------------------------------------------------------------


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
    base_api_url = f"{_normalize_api_base_url(api_base_url)}/api/0"
    headers = {"Authorization": f"Bearer {auth_token}", "Accept": "application/json"}

    # --- Project fan-out (custom iterator) ---
    if endpoint_config.is_project_fanout:
        return _make_source_response(
            endpoint_config,
            lambda: _iter_project_fanout_rows(
                base_api_url=base_api_url,
                headers=headers,
                organization_slug=organization_slug,
                endpoint=endpoint,
            ),
        )

    # --- Issue fan-out ---
    if endpoint_config.is_issue_fanout:
        # issue_tag_values needs tag-key discovery per issue, so it stays on
        # a custom iterator. issue_events/issue_hashes use rest_api_resources
        # dependent-resource config (parent=issues, child resolves issue_id).
        if endpoint == "issue_tag_values":
            return _make_source_response(
                endpoint_config,
                lambda: _iter_issue_tag_values_rows(
                    base_api_url=base_api_url,
                    headers=headers,
                    organization_slug=organization_slug,
                ),
            )

        return _build_issue_dependent_source(
            endpoint=endpoint,
            endpoint_config=endpoint_config,
            organization_slug=organization_slug,
            auth_token=auth_token,
            base_api_url=base_api_url,
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )

    # --- Flat org-level endpoints (via rest_api_resources) ---
    config: RESTAPIConfig = {
        "client": {
            "base_url": base_api_url,
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
    return _make_source_response(endpoint_config, lambda: resources[0])


def _build_issue_dependent_source(
    *,
    endpoint: str,
    endpoint_config: SentryEndpointConfig,
    organization_slug: str,
    auth_token: str,
    base_api_url: str,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Any,
) -> SourceResponse:
    """Build a dependent-resource config where `issues` is the parent and
    the child endpoint resolves `{issue_id}` from each parent row."""
    issues_config = SENTRY_ENDPOINTS["issues"]

    parent_resource: EndpointResource = {
        "name": "issues",
        "table_name": "issues",
        "primary_key": "id",
        "write_disposition": "replace",
        "endpoint": {
            "path": issues_config.path.format(organization_slug=organization_slug),
            "params": {"limit": issues_config.page_size, "query": "", "sort": "date"},
        },
        "table_format": "delta",
    }

    child_resource: EndpointResource = {
        "name": endpoint,
        "table_name": endpoint,
        "primary_key": endpoint_config.primary_key,
        "write_disposition": "replace",
        "include_from_parent": ["id"],
        "endpoint": {
            "path": endpoint_config.path,
            "params": {
                "organization_slug": organization_slug,
                "issue_id": {
                    "type": "resolve",
                    "resource": "issues",
                    "field": "id",
                },
                "limit": endpoint_config.page_size,
            },
        },
        "table_format": "delta",
    }

    config: RESTAPIConfig = {
        "client": {
            "base_url": base_api_url,
            "auth": {"type": "bearer", "token": auth_token},
            "headers": {"Accept": "application/json"},
            "paginator": SentryPaginator(),
        },
        "resource_defaults": {},
        "resources": [parent_resource, child_resource],
    }

    resources = rest_api_resources(config, team_id, job_id, db_incremental_field_last_value)
    child_dlt_resource = next(r for r in resources if getattr(r, "name", None) == endpoint)

    def _ensure_issue_id(row: dict[str, Any]) -> dict[str, Any]:
        if "id" in row and "issue_id" not in row:
            row["issue_id"] = row["id"]
        return row

    child_dlt_resource = child_dlt_resource.add_map(_ensure_issue_id)
    return _make_source_response(endpoint_config, lambda: child_dlt_resource)
