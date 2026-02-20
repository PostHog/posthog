from collections.abc import Iterator
from datetime import date, datetime
from typing import Any, Optional

import requests
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from posthog.temporal.data_imports.sources.mailchimp.settings import MAILCHIMP_ENDPOINTS


def extract_data_center(api_key: str) -> str:
    """Extract data center from Mailchimp API key.

    Mailchimp API keys are in format: key-dc (e.g., "0123456789abcdef-us6")
    The data center suffix determines the API subdomain.
    """
    if "-" not in api_key:
        raise ValueError("Invalid Mailchimp API key format. Expected format: key-dc")
    return api_key.split("-")[-1]


def _format_incremental_value(value: Any) -> str:
    """Format incremental field value as ISO string for Mailchimp API filters."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    return str(value)


class MailchimpPaginator(BasePaginator):
    """Paginator for Mailchimp API using offset/count pagination."""

    def __init__(self, page_size: int = 1000) -> None:
        super().__init__()
        self._page_size = page_size
        self._offset = 0
        self._total_items: int | None = None

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        res = response.json()

        if not res:
            self._has_next_page = False
            return

        self._total_items = res.get("total_items", 0)
        self._offset += self._page_size
        self._has_next_page = self._offset < self._total_items

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}

        request.params["offset"] = self._offset
        request.params["count"] = self._page_size


def get_resource(
    name: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> EndpointResource:
    """Build endpoint resource configuration for a Mailchimp endpoint."""
    config = MAILCHIMP_ENDPOINTS[name]

    params: dict[str, Any] = {
        "count": config.page_size,
    }

    # Add incremental filter for supported endpoints
    if should_use_incremental_field and db_incremental_field_last_value:
        formatted_value = _format_incremental_value(db_incremental_field_last_value)
        field = incremental_field or config.default_incremental_field

        if name == "campaigns":
            if field == "create_time":
                params["since_create_time"] = formatted_value
            elif field == "send_time":
                params["since_send_time"] = formatted_value
        elif name == "reports" and field == "send_time":
            params["since_send_time"] = formatted_value

    return {
        "name": config.name,
        "table_name": config.name,
        "primary_key": "id",
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": {
            "data_selector": config.data_selector,
            "path": config.path,
            "params": params,
        },
        "table_format": "delta",
    }


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Validate Mailchimp API credentials by making a test request."""
    try:
        dc = extract_data_center(api_key)
    except ValueError as e:
        return False, str(e)

    url = f"https://{dc}.api.mailchimp.com/3.0/ping"
    headers = {
        "Authorization": f"apikey {api_key}",
        "Accept": "application/json",
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            return True, None

        if response.status_code == 401:
            return False, "Invalid API key"

        if response.status_code == 403:
            return False, "API key does not have required permissions"

        try:
            error_data = response.json()
            detail = error_data.get("detail", response.text)
            return False, detail
        except Exception:
            pass

        return False, response.text
    except requests.exceptions.RequestException as e:
        return False, str(e)


def _fetch_all_lists(api_key: str, dc: str) -> list[dict[str, Any]]:
    """Fetch all lists/audiences from Mailchimp."""
    lists: list[dict[str, Any]] = []
    offset = 0
    page_size = 1000

    headers = {
        "Authorization": f"apikey {api_key}",
        "Accept": "application/json",
    }

    while True:
        response = requests.get(
            f"https://{dc}.api.mailchimp.com/3.0/lists",
            headers=headers,
            params={"count": page_size, "offset": offset},
            timeout=120,
        )
        response.raise_for_status()

        data = response.json()
        lists.extend(data.get("lists", []))

        total_items = data.get("total_items", 0)
        offset += page_size

        if offset >= total_items:
            break

    return lists


def _fetch_contacts_for_list(
    api_key: str,
    dc: str,
    list_id: str,
    since_last_changed: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Fetch all contacts for a specific list with pagination."""
    offset = 0
    page_size = 1000

    headers = {
        "Authorization": f"apikey {api_key}",
        "Accept": "application/json",
    }

    while True:
        params: dict[str, str | int] = {
            "count": page_size,
            "offset": offset,
        }
        if since_last_changed:
            params["since_last_changed"] = since_last_changed

        response = requests.get(
            f"https://{dc}.api.mailchimp.com/3.0/lists/{list_id}/members",
            headers=headers,
            params=params,
            timeout=120,
        )
        response.raise_for_status()

        data = response.json()
        contacts = data.get("members", [])

        for contact in contacts:
            contact["list_id"] = list_id
            yield contact

        total_items = data.get("total_items", 0)
        offset += page_size

        if offset >= total_items or not contacts:
            break


def _get_contacts_iterator(
    api_key: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[dict[str, Any]]:
    """Fetch contacts from all lists."""
    dc = extract_data_center(api_key)

    since_last_changed: str | None = None
    if should_use_incremental_field and db_incremental_field_last_value:
        since_last_changed = _format_incremental_value(db_incremental_field_last_value)

    lists = _fetch_all_lists(api_key, dc)

    for lst in lists:
        list_id = lst["id"]
        yield from _fetch_contacts_for_list(api_key, dc, list_id, since_last_changed)


def mailchimp_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    """Create a Mailchimp data source for the specified endpoint."""
    endpoint_config = MAILCHIMP_ENDPOINTS[endpoint]

    # Contacts endpoint is special - fetches from all lists
    if endpoint == "contacts":
        return SourceResponse(
            name=endpoint,
            items=lambda: _get_contacts_iterator(
                api_key,
                should_use_incremental_field,
                db_incremental_field_last_value,
            ),
            primary_keys=["list_id", "id"],
            partition_count=1,
            partition_size=1,
            partition_mode="datetime" if endpoint_config.partition_key else None,
            partition_format="week" if endpoint_config.partition_key else None,
            partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        )

    dc = extract_data_center(api_key)

    config: RESTAPIConfig = {
        "client": {
            "base_url": f"https://{dc}.api.mailchimp.com/3.0",
            "auth": {
                "type": "api_key",
                "api_key": f"apikey {api_key}",
                "name": "Authorization",
                "location": "header",
            },
            "headers": {
                "Accept": "application/json",
            },
            "paginator": MailchimpPaginator(page_size=endpoint_config.page_size),
        },
        "resource_defaults": {
            "primary_key": "id",
            "write_disposition": "replace",
            "endpoint": {
                "params": {
                    "count": endpoint_config.page_size,
                },
            },
        },
        "resources": [
            get_resource(
                endpoint,
                should_use_incremental_field,
                db_incremental_field_last_value,
                incremental_field,
            )
        ],
    }

    resources = rest_api_resources(config, team_id, job_id, db_incremental_field_last_value)
    assert len(resources) == 1
    resource = resources[0]

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
