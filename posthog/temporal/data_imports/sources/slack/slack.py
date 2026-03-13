import datetime
from collections.abc import Callable, Iterable, Iterator
from typing import Any, Optional

import requests
import structlog
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.auth import BearerTokenAuth
from dlt.sources.helpers.rest_client.paginators import BasePaginator
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.pipelines.pipeline.typings import SortMode, SourceResponse
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from posthog.temporal.data_imports.sources.slack.settings import ENDPOINTS, messages_endpoint_config

logger = structlog.get_logger(__name__)


class SlackRetryableError(Exception):
    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


def _wait_with_retry_after(retry_state: RetryCallState) -> float:
    exception = retry_state.outcome and retry_state.outcome.exception()
    if isinstance(exception, SlackRetryableError) and exception.retry_after is not None:
        return float(exception.retry_after)
    return wait_exponential_jitter(initial=1, max=30)(retry_state)


@retry(
    retry=retry_if_exception_type(
        (SlackRetryableError, requests.exceptions.ConnectionError, requests.exceptions.Timeout)
    ),
    stop=stop_after_attempt(5),
    wait=_wait_with_retry_after,
    reraise=True,
)
def _slack_get(url: str, **kwargs: Any) -> requests.Response:
    response = requests.get(url, **kwargs)
    if response.status_code == 429:
        retry_after = int(response.headers.get("Retry-After", 1))
        logger.warning("Slack API rate limited", url=url, retry_after=retry_after)
        raise SlackRetryableError("Slack: rate limited", retry_after=retry_after)
    if response.status_code >= 500:
        raise SlackRetryableError(f"Slack: server error {response.status_code}")
    return response


class SlackCursorPaginator(BasePaginator):
    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        res = response.json()

        self._next_cursor = None

        if not res or not res.get("ok"):
            error = (res or {}).get("error", "unknown_error")
            raise Exception(f"Slack API error: {error}")

        next_cursor = res.get("response_metadata", {}).get("next_cursor", "")

        if next_cursor:
            self._next_cursor = next_cursor
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if self._next_cursor:
            request.params = {**(request.params or {}), "cursor": self._next_cursor}


def get_resource(name: str, should_use_incremental_field: bool) -> EndpointResource:
    if name == "$channels":
        return {
            "name": "$channels",
            "table_name": "$channels",
            "primary_key": "id",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "channels",
                "path": "conversations.list",
                "params": {
                    "types": "public_channel,private_channel",
                    "limit": 999,
                    "exclude_archived": "false",
                },
            },
            "table_format": "delta",
        }

    if name == "$users":
        return {
            "name": "$users",
            "table_name": "$users",
            "primary_key": "id",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "members",
                "path": "users.list",
                "params": {
                    "limit": 999,
                },
            },
            "table_format": "delta",
        }

    raise ValueError(f"Unknown Slack resource: {name}")


def _fetch_all_channels(access_token: str) -> list[dict[str, Any]]:
    channels: list[dict[str, Any]] = []
    has_more = True
    cursor: str | None = None
    url = "https://slack.com/api/conversations.list"
    headers = {"Authorization": f"Bearer {access_token}"}

    while has_more:
        params: dict[str, Any] = {
            "types": "public_channel,private_channel",
            "limit": 999,
            "exclude_archived": "false",
        }
        if cursor:
            params["cursor"] = cursor

        response = _slack_get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if not data.get("ok"):
            error = data.get("error", "unknown_error")
            raise Exception(f"Slack API error fetching channels: {error}")

        channels.extend(data.get("channels", []))

        cursor = data.get("response_metadata", {}).get("next_cursor", "") or None
        has_more = cursor is not None

    return channels


def _fetch_messages_for_channel(
    access_token: str,
    channel_id: str,
    oldest_ts: str | None = None,
) -> Iterator[dict[str, Any]]:
    has_more = True
    cursor: str | None = None
    url = "https://slack.com/api/conversations.history"
    headers = {"Authorization": f"Bearer {access_token}"}

    while has_more:
        params: dict[str, Any] = {
            "channel": channel_id,
            "limit": 999,
        }
        if oldest_ts:
            params["oldest"] = oldest_ts
        if cursor:
            params["cursor"] = cursor

        response = _slack_get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if not data.get("ok"):
            error = data.get("error", "unknown_error")
            raise Exception(f"Slack API error fetching messages for channel {channel_id}: {error}")

        messages = data.get("messages", [])
        for msg in messages:
            msg["channel_id"] = channel_id
            yield msg

        cursor = data.get("response_metadata", {}).get("next_cursor", "") or None
        has_more = cursor is not None


def _fetch_thread_replies(
    access_token: str,
    channel_id: str,
    thread_ts: str,
) -> Iterator[dict[str, Any]]:
    """Fetch replies for a single thread, excluding the parent message."""
    has_more = True
    cursor: str | None = None
    url = "https://slack.com/api/conversations.replies"
    headers = {"Authorization": f"Bearer {access_token}"}

    while has_more:
        params: dict[str, Any] = {
            "channel": channel_id,
            "ts": thread_ts,
            "limit": 999,
        }
        if cursor:
            params["cursor"] = cursor

        response = _slack_get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if not data.get("ok"):
            error = data.get("error", "unknown_error")
            if error == "thread_not_found":
                logger.info("Thread not found, skipping", channel_id=channel_id, thread_ts=thread_ts)
                return
            raise Exception(f"Slack API error fetching thread replies for {channel_id}/{thread_ts}: {error}")

        for msg in data.get("messages", []):
            # conversations.replies includes the parent message — skip it since it was already yielded by _fetch_messages_for_channel
            if msg.get("ts") == thread_ts and msg.get("thread_ts") == thread_ts:
                continue
            msg["channel_id"] = channel_id
            yield msg

        cursor = data.get("response_metadata", {}).get("next_cursor", "") or None
        has_more = cursor is not None


def get_channels(access_token: str) -> list[dict[str, str]]:
    """Return channel id + name pairs for all accessible channels."""
    return [{"id": ch["id"], "name": ch["name"]} for ch in _fetch_all_channels(access_token)]


def _add_timestamp(msg: dict[str, Any]) -> dict[str, Any]:
    ts = msg.get("ts")
    if ts:
        msg["timestamp"] = datetime.datetime.fromtimestamp(float(ts), tz=datetime.UTC).isoformat()
    return msg


def _channel_messages_generator(
    access_token: str,
    channel_id: str,
    oldest_ts: str | None = None,
) -> Iterator[dict[str, Any]]:
    for msg in _fetch_messages_for_channel(access_token, channel_id, oldest_ts=oldest_ts):
        yield _add_timestamp(msg)
        if msg.get("reply_count", 0) > 0:
            for reply in _fetch_thread_replies(access_token, channel_id, msg["ts"]):
                yield _add_timestamp(reply)


def slack_source(
    access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
    channel_id: str | None = None,
) -> SourceResponse:
    items: Callable[[], Iterable[Any]]
    sort_mode: SortMode = "asc"

    if endpoint in ENDPOINTS:
        # Metadata endpoints ($channels, $users) — served via REST
        endpoint_config = ENDPOINTS[endpoint]
        config: RESTAPIConfig = {
            "client": {
                "base_url": "https://slack.com/api/",
                "auth": BearerTokenAuth(token=access_token),
                "paginator": SlackCursorPaginator(),
            },
            "resource_defaults": {
                "primary_key": "id",
                "write_disposition": "replace",
            },
            "resources": [get_resource(endpoint, should_use_incremental_field)],
        }

        resources = rest_api_resources(config, team_id, job_id, None)
        assert len(resources) == 1
        resource = resources[0]
        items = lambda: resource
    else:
        # Per-channel message endpoint
        endpoint_config = messages_endpoint_config()
        sort_mode = "desc"

        if channel_id is None:
            raise Exception(f"channel_not_found: {endpoint}")

        oldest_ts: str | None = None
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            # Known limitation: incremental polling only fetches thread replies for parent messages
            # returned by conversations.history in this window. Replies added to older parent threads
            # (parent ts < oldest_ts) are intentionally not captured here and are expected to be
            # addressed by webhook sources.
            oldest_ts = str(db_incremental_field_last_value.timestamp())

        resolved_id = channel_id
        resolved_oldest_ts = oldest_ts
        items = lambda: _channel_messages_generator(access_token, resolved_id, oldest_ts=resolved_oldest_ts)

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=endpoint_config.primary_keys,
        partition_keys=endpoint_config.partition_keys,
        partition_mode=endpoint_config.partition_mode,
        partition_format=endpoint_config.partition_format,
        sort_mode=sort_mode,
    )


def validate_credentials(access_token: str) -> bool:
    url = "https://slack.com/api/auth.test"
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        response = _slack_get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("ok", False)
    except Exception:
        return False
