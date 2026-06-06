import dataclasses
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any, Optional

from requests import Request, Response
from requests.exceptions import RequestException

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resource
from posthog.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.mailchimp.settings import MAILCHIMP_ENDPOINTS


@dataclasses.dataclass
class MailchimpResumeConfig:
    """Resume state for Mailchimp endpoints.

    - ``contacts`` fans out over audience lists and paginates members within
      each; its checkpoint is ``(list_id, offset)``.
    - ``lists``/``campaigns``/``reports`` go through the shared ``rest_api_resource``
      path using ``MailchimpPaginator`` (offset/count); their checkpoint is just
      ``offset`` and ``list_id`` is ``None``.

    On resume we re-request the saved page; duplicates are deduped by the
    primary key.
    """

    offset: int
    list_id: Optional[str] = None


def extract_data_center(api_key: str) -> str:
    """Extract data center from Mailchimp API key.

    Mailchimp API keys are in format: key-dc (e.g., "0123456789abcdef-us6")
    The data center suffix determines the API subdomain.
    """
    if "-" not in api_key:
        raise ValueError("Invalid Mailchimp API key format. Expected format: key-dc")
    dc = api_key.split("-")[-1]
    if not dc.isalnum():
        raise ValueError("Invalid Mailchimp API key format. Expected format: key-dc")
    return dc


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

    def init_request(self, request: Request) -> None:
        # Always set offset/count so that (a) a seeded resume offset is honoured
        # on the first request, and (b) fresh runs start from offset=0 explicitly.
        if request.params is None:
            request.params = {}
        request.params["offset"] = self._offset
        request.params["count"] = self._page_size

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

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # rest_client only calls this when has_next_page is True, so ``_offset``
        # already points at the page we still need to fetch.
        return {"offset": self._offset}

    def set_resume_state(self, state: dict[str, Any]) -> None:
        offset = state.get("offset")
        if offset is not None:
            self._offset = int(offset)
            self._has_next_page = True


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
        response = make_tracked_session().get(url, headers=headers, timeout=10)

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
    except RequestException as e:
        return False, str(e)


def _fetch_all_lists(api_key: str, dc: str) -> list[dict[str, Any]]:
    """Fetch all lists/audiences from Mailchimp."""
    lists: list[dict[str, Any]] = []
    offset = 0
    page_size = 1000

    # One session for the whole pagination loop so urllib3's connection
    # pool keeps the TLS connection warm across pages.
    session = make_tracked_session(
        headers={
            "Authorization": f"apikey {api_key}",
            "Accept": "application/json",
        }
    )

    while True:
        response = session.get(
            f"https://{dc}.api.mailchimp.com/3.0/lists",
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
    since_last_changed: str | None,
    resumable_source_manager: ResumableSourceManager[MailchimpResumeConfig],
    start_offset: int = 0,
) -> Iterator[dict[str, Any]]:
    """Fetch all contacts for a specific list with pagination."""
    offset = start_offset
    page_size = 1000

    # One session for the whole pagination loop — see `_fetch_all_lists`.
    session = make_tracked_session(
        headers={
            "Authorization": f"apikey {api_key}",
            "Accept": "application/json",
        }
    )

    while True:
        params: dict[str, str | int] = {
            "count": page_size,
            "offset": offset,
        }
        if since_last_changed:
            params["since_last_changed"] = since_last_changed

        response = session.get(
            f"https://{dc}.api.mailchimp.com/3.0/lists/{list_id}/members",
            params=params,
            timeout=120,
        )
        response.raise_for_status()

        data = response.json()
        contacts = data.get("members", [])

        if not contacts:
            break

        # Save the checkpoint for the page we just fetched *before* yielding.
        # On resume we re-fetch this page — duplicates are deduped by (list_id, id).
        resumable_source_manager.save_state(MailchimpResumeConfig(list_id=list_id, offset=offset))

        for contact in contacts:
            contact["list_id"] = list_id
            yield contact

        total_items = data.get("total_items", 0)
        offset += page_size

        if offset >= total_items:
            break


def _get_contacts_iterator(
    api_key: str,
    resumable_source_manager: ResumableSourceManager[MailchimpResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[dict[str, Any]]:
    """Fetch contacts from all lists."""
    dc = extract_data_center(api_key)

    since_last_changed: str | None = None
    if should_use_incremental_field and db_incremental_field_last_value:
        since_last_changed = _format_incremental_value(db_incremental_field_last_value)

    lists = _fetch_all_lists(api_key, dc)

    # Only honour the saved checkpoint if its list_id still exists; otherwise fall back to a fresh run.
    resume_config: MailchimpResumeConfig | None = None
    if resumable_source_manager.can_resume():
        loaded = resumable_source_manager.load_state()
        if loaded is not None and any(lst["id"] == loaded.list_id for lst in lists):
            resume_config = loaded

    for lst in lists:
        list_id = lst["id"]

        if resume_config is not None:
            if list_id != resume_config.list_id:
                continue
            start_offset = resume_config.offset
            resume_config = None
        else:
            start_offset = 0

        yield from _fetch_contacts_for_list(
            api_key,
            dc,
            list_id,
            since_last_changed,
            resumable_source_manager,
            start_offset=start_offset,
        )


def mailchimp_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MailchimpResumeConfig],
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
                resumable_source_manager,
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

    # ``lists``/``campaigns``/``reports`` all paginate by offset/count and can
    # resume by seeding the paginator with the last un-fetched offset.
    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None and resume_config.offset > 0:
            initial_paginator_state = {"offset": resume_config.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to — matches the
        # klaviyo/reddit_ads convention; Redis TTL handles cleanup on completion.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(MailchimpResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

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
