import re
import time
from collections.abc import Callable, Iterator
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
# Low-level HTTP helpers (used only by issue_tag_values custom fan-out)
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
# Issue tag-values fan-out (custom iterator — requires two-level fan-out:
# issues → tags-per-issue → values-per-tag.  Can't be expressed as a single
# parent→child dependency in rest_api_resources.)
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
        issue_id = str(issue["id"])

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
# Shared helpers
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


def _rename_parent_fields(parent_name: str, renames: dict[str, str]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Build a row mapper that renames ``_<parent>_<field>`` keys injected by
    ``include_from_parent`` into the desired column names.

    ``renames`` maps parent field names to target column names, e.g.
    ``{"id": "project_id", "slug": "project_slug"}``.
    """
    key_map = {f"_{parent_name}_{src}": dst for src, dst in renames.items()}

    def _mapper(row: dict[str, Any]) -> dict[str, Any]:
        for prefixed_key, target_key in key_map.items():
            if prefixed_key in row:
                row[target_key] = row.pop(prefixed_key)
        return row

    return _mapper


# ---------------------------------------------------------------------------
# Dependent-resource builder (project fan-out + issue fan-out)
# ---------------------------------------------------------------------------


def _build_dependent_source(
    *,
    parent_name: str,
    child_endpoint: str,
    organization_slug: str,
    auth_token: str,
    base_api_url: str,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Any,
    resolve_param: str,
    resolve_field: str,
    include_from_parent: list[str],
    row_mapper: Callable[[dict[str, Any]], dict[str, Any]],
    should_use_incremental_field: bool = False,
    incremental_field: str | None = None,
) -> SourceResponse:
    """Build a dependent-resource config where ``parent_name`` is the parent
    and the child endpoint resolves one path placeholder from each parent row.

    Uses ``.replace()`` for ``{organization_slug}`` so that only the resolved
    placeholder remains for ``process_parent_data_item`` to format.
    """
    parent_config = SENTRY_ENDPOINTS[parent_name]
    child_config = SENTRY_ENDPOINTS[child_endpoint]

    parent_params: dict[str, Any] = {"limit": parent_config.page_size}
    if parent_name == "issues":
        parent_params.update({"query": "", "sort": "date"})

    parent_resource: EndpointResource = {
        "name": parent_name,
        "table_name": parent_name,
        "primary_key": parent_config.primary_key,
        "write_disposition": "replace",
        "endpoint": {
            "path": parent_config.path.format(organization_slug=organization_slug),
            "params": parent_params,
        },
        "table_format": "delta",
    }

    child_path = child_config.path.replace("{organization_slug}", organization_slug)

    child_endpoint_config: dict[str, Any] = {
        "path": child_path,
        "params": {
            resolve_param: {
                "type": "resolve",
                "resource": parent_name,
                "field": resolve_field,
            },
            "limit": child_config.page_size,
        },
    }
    if (
        should_use_incremental_field
        and child_config.incremental_fields
        and (incremental_field or child_config.default_incremental_field)
    ):
        cursor = incremental_field or child_config.default_incremental_field
        child_endpoint_config["incremental"] = {
            "cursor_path": cursor,
            "start_param": "start",
            "initial_value": "1970-01-01T00:00:00Z",
        }

    use_merge = bool(should_use_incremental_field and child_config.incremental_fields)
    child_resource: EndpointResource = {
        "name": child_endpoint,
        "table_name": child_endpoint,
        "primary_key": child_config.primary_key,
        "write_disposition": ({"disposition": "merge", "strategy": "upsert"} if use_merge else "replace"),
        "include_from_parent": include_from_parent,
        "endpoint": child_endpoint_config,
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
    child_dlt_resource = next(r for r in resources if getattr(r, "name", None) == child_endpoint)
    child_dlt_resource = child_dlt_resource.add_map(row_mapper)
    return _make_source_response(child_config, lambda: child_dlt_resource)


# Row mappers for the two fan-out families.
_map_project_parent_fields = _rename_parent_fields("projects", {"id": "project_id", "slug": "project_slug"})
_map_issue_parent_fields = _rename_parent_fields("issues", {"id": "issue_id"})


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

    common_kwargs = {
        "organization_slug": organization_slug,
        "auth_token": auth_token,
        "base_api_url": base_api_url,
        "team_id": team_id,
        "job_id": job_id,
        "db_incremental_field_last_value": db_incremental_field_last_value,
        "should_use_incremental_field": should_use_incremental_field,
        "incremental_field": incremental_field,
    }

    # --- Project fan-out (parent=projects, resolve project_slug) ---
    if endpoint_config.is_project_fanout:
        return _build_dependent_source(
            parent_name="projects",
            child_endpoint=endpoint,
            resolve_param="project_slug",
            resolve_field="slug",
            include_from_parent=["id", "slug"],
            row_mapper=_map_project_parent_fields,
            **common_kwargs,
        )

    # --- Issue fan-out ---
    if endpoint_config.is_issue_fanout:
        # issue_tag_values needs two-level fan-out (issues → tags → values)
        # which can't be expressed as a single parent→child dependency.
        if endpoint == "issue_tag_values":
            headers = {"Authorization": f"Bearer {auth_token}", "Accept": "application/json"}
            return _make_source_response(
                endpoint_config,
                lambda: _iter_issue_tag_values_rows(
                    base_api_url=base_api_url,
                    headers=headers,
                    organization_slug=organization_slug,
                ),
            )

        return _build_dependent_source(
            parent_name="issues",
            child_endpoint=endpoint,
            resolve_param="issue_id",
            resolve_field="id",
            include_from_parent=["id"],
            row_mapper=_map_issue_parent_fields,
            **common_kwargs,
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
    if len(resources) != 1:
        raise ValueError(f"Expected 1 resource for endpoint '{endpoint}', got {len(resources)}")
    return _make_source_response(endpoint_config, lambda: resources[0])
