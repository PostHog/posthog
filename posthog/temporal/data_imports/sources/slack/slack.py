import datetime
import dataclasses
from collections.abc import AsyncIterable, Callable, Iterable, Iterator
from typing import Any, Optional

import orjson
import pyarrow as pa
import requests
import structlog
from asgiref.sync import async_to_sync
from requests import Request, Response
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.pipelines.pipeline.typings import SortMode, SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resource
from posthog.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from posthog.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from posthog.temporal.data_imports.sources.slack.settings import ENDPOINTS, messages_endpoint_config

logger = structlog.get_logger(__name__)


@dataclasses.dataclass
class SlackResumeConfig:
    channel_id: str
    next_cursor: str
    oldest_ts: str | None = None


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
    response = make_tracked_session().get(url, **kwargs)
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


def _fetch_messages_page(
    access_token: str,
    channel_id: str,
    oldest_ts: str | None,
    cursor: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch a single page of messages for a channel. Returns (messages, next_cursor)."""
    url = "https://slack.com/api/conversations.history"
    headers = {"Authorization": f"Bearer {access_token}"}

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

    next_cursor = data.get("response_metadata", {}).get("next_cursor", "") or None
    return messages, next_cursor


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
            # conversations.replies includes the parent message — skip it since it was already yielded by the channel messages page
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
    resumable_source_manager: ResumableSourceManager[SlackResumeConfig],
    oldest_ts: str | None = None,
) -> Iterator[dict[str, Any]]:
    cursor: str | None = None
    effective_oldest_ts = oldest_ts

    # Only honor state scoped to this channel — guards against reuse of a job_id across schemas.
    resume_config = resumable_source_manager.load_state()
    if resume_config is not None and resume_config.channel_id == channel_id:
        cursor = resume_config.next_cursor
        effective_oldest_ts = resume_config.oldest_ts

    has_more = True
    while has_more:
        messages, next_cursor = _fetch_messages_page(
            access_token, channel_id, oldest_ts=effective_oldest_ts, cursor=cursor
        )

        for msg in messages:
            yield _add_timestamp(msg)
            if msg.get("reply_count", 0) > 0:
                for reply in _fetch_thread_replies(access_token, channel_id, msg["ts"]):
                    yield _add_timestamp(reply)

        cursor = next_cursor
        has_more = cursor is not None

        if cursor is not None:
            # Checkpoint: all messages on this page and their thread replies have been yielded.
            # On resume we start from next_cursor, so no duplication of parent messages.
            resumable_source_manager.save_state(
                SlackResumeConfig(
                    channel_id=channel_id,
                    next_cursor=cursor,
                    oldest_ts=effective_oldest_ts,
                )
            )


def _webhook_table_transformer(table: pa.Table) -> pa.Table:
    if "event" not in table.column_names:
        return table_from_py_list([])
    event_col = table.column("event").to_pylist()

    # Deduplicate by (ts, channel) — Slack retries delivery on timeout, so the same
    # message event can arrive more than once within a single sync batch.
    seen: set[tuple[str, str]] = set()
    rows = []
    for event_data in event_col:
        if event_data is None:
            continue
        event: dict[str, Any] = orjson.loads(event_data) if isinstance(event_data, (str, bytes)) else dict(event_data)
        channel = event.get("channel", "")
        ts = event.get("ts")
        # The warehouse partitions on `timestamp`, so a row without `ts` is unusable.
        # Slack guarantees every `message.channels` / `message.groups` event carries one,
        # so a missing value indicates a malformed payload or upstream change — surface
        # it loudly rather than write rows that can never be queried correctly.
        if not ts:
            raise ValueError(f"Slack webhook event for channel {channel!r} is missing required `ts`")
        key = (ts, channel)
        if key in seen:
            continue
        seen.add(key)
        event["channel_id"] = channel
        event["timestamp"] = datetime.datetime.fromtimestamp(float(ts), tz=datetime.UTC).isoformat()
        rows.append(event)
    return table_from_py_list(rows)


def slack_source(
    access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    webhook_source_manager: WebhookSourceManager,
    resumable_source_manager: ResumableSourceManager[SlackResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
    channel_id: str | None = None,
) -> SourceResponse:
    items: Callable[[], Iterable[Any] | AsyncIterable[Any]]
    sort_mode: SortMode = "asc"

    if endpoint in ENDPOINTS:
        # Metadata endpoints ($channels, $users) — served via REST, no webhook support
        endpoint_config = ENDPOINTS[endpoint]
        config: RESTAPIConfig = {
            "client": {
                "base_url": "https://slack.com/api/",
                "auth": BearerTokenAuth(token=access_token),
                "paginator": SlackCursorPaginator(),
            },
            "resource_defaults": {
                "write_disposition": "replace",
            },
            "resources": [get_resource(endpoint, should_use_incremental_field)],
        }

        resource = rest_api_resource(config, team_id, job_id, None)
        items = lambda: resource
    else:
        # Per-channel message endpoint
        endpoint_config = messages_endpoint_config()
        sort_mode = "desc"

        if channel_id is None:
            raise Exception(f"channel_not_found: {endpoint}")

        webhook_enabled = async_to_sync(webhook_source_manager.webhook_enabled)()

        oldest_ts: str | None = None
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            # Known limitation: incremental polling only fetches thread replies for parent messages
            # returned by conversations.history in this window. Replies added to older parent threads
            # (parent ts < oldest_ts) are intentionally not captured here and are expected to be
            # addressed by webhook sources.
            oldest_ts = str(db_incremental_field_last_value.timestamp())

        resolved_id = channel_id
        resolved_oldest_ts = oldest_ts

        def channel_items() -> Iterable[Any] | AsyncIterable[Any]:
            if webhook_enabled:
                return webhook_source_manager.get_items(table_transformer=_webhook_table_transformer)
            return _channel_messages_generator(
                access_token, resolved_id, resumable_source_manager, oldest_ts=resolved_oldest_ts
            )

        items = channel_items

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
