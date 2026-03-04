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
from posthog.temporal.data_imports.sources.sentry.settings import SENTRY_ENDPOINTS

DEFAULT_MAX_PROJECTS_TO_SYNC = 200
DEFAULT_MAX_ISSUES_TO_FANOUT = 500
DEFAULT_MAX_PAGES_PER_PARENT = 10
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30
DEFAULT_MAX_RETRIES = 3


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


def _request_with_retry(
    url: str,
    headers: dict[str, str],
    params: dict[str, Any] | None,
    timeout: int,
    max_retries: int,
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

        backoff = 2**attempt
        time.sleep(backoff)

    if last_response is not None:
        return last_response
    if last_exception is not None:
        raise last_exception
    raise RuntimeError("Unexpected request retry state")


def _extract_next_url(link_header: str) -> str | None:
    if not link_header:
        return None

    for part in link_header.split(","):
        part = part.strip()
        next_match = re.search(r'<([^>]+)>;\s*rel="next"', part)
        if not next_match:
            continue
        results_match = re.search(r'results="(true|false)"', part)
        has_results = results_match and results_match.group(1) == "true"
        if has_results:
            return next_match.group(1)
        return None
    return None


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        return [payload]
    return []


def _coerce_positive_int(value: int | None, fallback: int) -> int:
    if value is None:
        return fallback
    return value if value > 0 else fallback


def _iter_endpoint_rows(
    base_api_url: str,
    path: str,
    headers: dict[str, str],
    params: dict[str, Any] | None,
    timeout: int,
    max_retries: int,
    max_pages: int | None = None,
) -> Iterator[dict[str, Any]]:
    url = urljoin(f"{base_api_url}/", path.lstrip("/"))
    current_params = params or {}
    pages_read = 0
    max_pages_to_read = max_pages if max_pages and max_pages > 0 else None

    while url:
        if max_pages_to_read is not None and pages_read >= max_pages_to_read:
            break

        response = _request_with_retry(
            url=url,
            headers=headers,
            params=current_params,
            timeout=timeout,
            max_retries=max_retries,
        )
        response.raise_for_status()

        payload = response.json()
        rows = _extract_rows(payload)
        yield from rows

        pages_read += 1
        next_url = _extract_next_url(response.headers.get("Link", ""))
        if not next_url:
            break
        url = urljoin(f"{base_api_url}/", next_url)
        current_params = None


def _add_common_fields(
    row: dict[str, Any],
    organization_slug: str,
    endpoint: str,
) -> dict[str, Any]:
    enriched = dict(row)
    enriched["organization_slug"] = organization_slug
    enriched["source_endpoint"] = endpoint
    return enriched


def _iter_project_fanout_rows(
    base_api_url: str,
    headers: dict[str, str],
    organization_slug: str,
    endpoint: str,
    max_projects_to_sync: int,
    max_pages_per_parent: int,
    timeout: int,
    max_retries: int,
) -> Iterator[dict[str, Any]]:
    endpoint_config = SENTRY_ENDPOINTS[endpoint]
    projects = _iter_endpoint_rows(
        base_api_url=base_api_url,
        path=f"/organizations/{organization_slug}/projects/",
        headers=headers,
        params={"limit": 100},
        timeout=timeout,
        max_retries=max_retries,
    )

    for index, project in enumerate(projects):
        if index >= max_projects_to_sync:
            break

        project_slug = project.get("slug")
        project_id = project.get("id")
        if not project_slug:
            continue

        path = endpoint_config.path.format(organization_slug=organization_slug, project_slug=project_slug)
        params: dict[str, Any] = {"limit": endpoint_config.page_size}

        for row in _iter_endpoint_rows(
            base_api_url=base_api_url,
            path=path,
            headers=headers,
            params=params,
            timeout=timeout,
            max_retries=max_retries,
            max_pages=max_pages_per_parent,
        ):
            enriched = _add_common_fields(row, organization_slug, endpoint)
            enriched["project_slug"] = project_slug
            enriched["project_id"] = project_id
            yield enriched


def _iter_issue_tag_values_rows(
    base_api_url: str,
    headers: dict[str, str],
    issue_id: str,
    organization_slug: str,
    endpoint: str,
    max_pages_per_parent: int,
    timeout: int,
    max_retries: int,
) -> Iterator[dict[str, Any]]:
    tags_path = f"/issues/{issue_id}/tags/"
    tags = list(
        _iter_endpoint_rows(
            base_api_url=base_api_url,
            path=tags_path,
            headers=headers,
            params={"limit": 100},
            timeout=timeout,
            max_retries=max_retries,
            max_pages=max_pages_per_parent,
        )
    )

    for tag in tags:
        tag_key = tag.get("key") or tag.get("id")
        if not isinstance(tag_key, str) or not tag_key:
            continue

        values_path = f"/issues/{issue_id}/tags/{quote(tag_key, safe='')}/values/"
        for row in _iter_endpoint_rows(
            base_api_url=base_api_url,
            path=values_path,
            headers=headers,
            params={"limit": 100},
            timeout=timeout,
            max_retries=max_retries,
            max_pages=max_pages_per_parent,
        ):
            enriched = _add_common_fields(row, organization_slug, endpoint)
            enriched["issue_id"] = issue_id
            enriched["tag_key"] = tag_key
            yield enriched


def _iter_issue_fanout_rows(
    base_api_url: str,
    headers: dict[str, str],
    organization_slug: str,
    endpoint: str,
    max_issues_to_fanout: int,
    max_pages_per_parent: int,
    timeout: int,
    max_retries: int,
) -> Iterator[dict[str, Any]]:
    issues = _iter_endpoint_rows(
        base_api_url=base_api_url,
        path=f"/organizations/{organization_slug}/issues/",
        headers=headers,
        params={"limit": 100, "query": "", "sort": "date"},
        timeout=timeout,
        max_retries=max_retries,
    )

    for index, issue in enumerate(issues):
        if index >= max_issues_to_fanout:
            break

        issue_id = str(issue.get("id", ""))
        if not issue_id:
            continue

        if endpoint == "issue_tag_values":
            yield from _iter_issue_tag_values_rows(
                base_api_url=base_api_url,
                headers=headers,
                issue_id=issue_id,
                organization_slug=organization_slug,
                endpoint=endpoint,
                max_pages_per_parent=max_pages_per_parent,
                timeout=timeout,
                max_retries=max_retries,
            )
            continue

        endpoint_config = SENTRY_ENDPOINTS[endpoint]
        path = endpoint_config.path.format(issue_id=issue_id)
        for row in _iter_endpoint_rows(
            base_api_url=base_api_url,
            path=path,
            headers=headers,
            params={"limit": endpoint_config.page_size},
            timeout=timeout,
            max_retries=max_retries,
            max_pages=max_pages_per_parent,
        ):
            enriched = _add_common_fields(row, organization_slug, endpoint)
            enriched["issue_id"] = issue_id
            yield enriched


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
    if config.is_project_fanout or config.is_issue_fanout:
        raise ValueError(f"Fan-out endpoint '{endpoint}' must use the fan-out iterator path")

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
    max_projects_to_sync: int | None = None,
    max_issues_to_fanout: int | None = None,
    max_pages_per_parent: int | None = None,
    request_timeout_seconds: int | None = None,
    max_retries: int | None = None,
) -> SourceResponse:
    endpoint_config = SENTRY_ENDPOINTS[endpoint]
    normalized_base_url = _normalize_api_base_url(api_base_url)

    max_projects = _coerce_positive_int(max_projects_to_sync, DEFAULT_MAX_PROJECTS_TO_SYNC)
    max_issues = _coerce_positive_int(max_issues_to_fanout, DEFAULT_MAX_ISSUES_TO_FANOUT)
    max_pages = _coerce_positive_int(max_pages_per_parent, DEFAULT_MAX_PAGES_PER_PARENT)
    timeout_seconds = _coerce_positive_int(request_timeout_seconds, DEFAULT_REQUEST_TIMEOUT_SECONDS)
    retry_count = _coerce_positive_int(max_retries, DEFAULT_MAX_RETRIES)

    headers = {"Authorization": f"Bearer {auth_token}", "Accept": "application/json"}
    base_api_url = f"{normalized_base_url}/api/0"

    if endpoint_config.is_project_fanout:
        return SourceResponse(
            name=endpoint,
            items=lambda: _iter_project_fanout_rows(
                base_api_url=base_api_url,
                headers=headers,
                organization_slug=organization_slug,
                endpoint=endpoint,
                max_projects_to_sync=max_projects,
                max_pages_per_parent=max_pages,
                timeout=timeout_seconds,
                max_retries=retry_count,
            ),
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

    if endpoint_config.is_issue_fanout:
        return SourceResponse(
            name=endpoint,
            items=lambda: _iter_issue_fanout_rows(
                base_api_url=base_api_url,
                headers=headers,
                organization_slug=organization_slug,
                endpoint=endpoint,
                max_issues_to_fanout=max_issues,
                max_pages_per_parent=max_pages,
                timeout=timeout_seconds,
                max_retries=retry_count,
            ),
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
    resource = resources[0].add_map(lambda row: _add_common_fields(row, organization_slug, endpoint))

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
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
