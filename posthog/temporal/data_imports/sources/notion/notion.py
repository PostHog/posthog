import dataclasses
from collections.abc import Iterator
from typing import Any, Literal, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.notion.settings import (
    NOTION_ENDPOINTS,
    NOTION_PAGE_SIZE,
    NotionEndpointConfig,
)

NOTION_BASE_URL = "https://api.notion.com"
# Pinned API version. 2022-06-28 keeps the stable "database" object semantics and is the most
# widely documented version; newer versions rename databases to "data sources".
NOTION_VERSION = "2022-06-28"

CHUNK_SIZE = 2000
CHUNK_SIZE_BYTES = 100 * 1024 * 1024

# Bounds for the fan-out streams (blocks/comments). Notion is rate limited to ~3 req/s, so deep
# recursion and unbounded child pagination would make syncs prohibitively slow.
MAX_BLOCK_DEPTH = 2
MAX_CHILD_PAGES_PER_PARENT = 50


class NotionRetryableError(Exception):
    pass


@dataclasses.dataclass
class NotionResumeConfig:
    next_cursor: str


def _get_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


@retry(
    retry=retry_if_exception_type((NotionRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _request(
    token: str,
    method: Literal["GET", "POST"],
    path: str,
    logger: FilteringBoundLogger,
    *,
    json_body: Optional[dict[str, Any]] = None,
    params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    url = f"{NOTION_BASE_URL}{path}"
    session = make_tracked_session(headers=_get_headers(token), redact_values=(token,))
    response = session.request(method, url, json=json_body, params=params, timeout=60)

    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After")
        raise NotionRetryableError(f"Notion rate limited: url={url}, retry_after={retry_after}")

    if response.status_code >= 500:
        raise NotionRetryableError(f"Notion API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Notion API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(token: str) -> tuple[bool, str | None]:
    try:
        session = make_tracked_session(headers=_get_headers(token), redact_values=(token,))
        response = session.get(f"{NOTION_BASE_URL}/v1/users/me", timeout=10)
    except Exception as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Notion integration token"
    if response.status_code == 403:
        return False, "Notion integration token is missing the required capabilities"
    return False, f"Notion API error: HTTP {response.status_code}"


def _search_body(object_filter: str, cursor: str | None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "filter": {"property": "object", "value": object_filter},
        "sort": {"timestamp": "last_edited_time", "direction": "ascending"},
        "page_size": NOTION_PAGE_SIZE,
    }
    if cursor:
        body["start_cursor"] = cursor
    return body


def _search_stream(
    token: str,
    config: NotionEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NotionResumeConfig],
) -> Iterator[Any]:
    assert config.object_filter is not None
    batcher = Batcher(logger=logger, chunk_size=CHUNK_SIZE, chunk_size_bytes=CHUNK_SIZE_BYTES)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume.next_cursor if resume is not None else None

    while True:
        data = _request(token, "POST", "/v1/search", logger, json_body=_search_body(config.object_filter, cursor))
        results = data.get("results", [])
        has_more = data.get("has_more", False)
        next_cursor = data.get("next_cursor")

        for item in results:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                if has_more and next_cursor:
                    resumable_source_manager.save_state(NotionResumeConfig(next_cursor=next_cursor))

        if not has_more or not next_cursor:
            break
        cursor = next_cursor

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def _users_stream(
    token: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NotionResumeConfig],
) -> Iterator[Any]:
    batcher = Batcher(logger=logger, chunk_size=CHUNK_SIZE, chunk_size_bytes=CHUNK_SIZE_BYTES)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume.next_cursor if resume is not None else None

    while True:
        params: dict[str, Any] = {"page_size": NOTION_PAGE_SIZE}
        if cursor:
            params["start_cursor"] = cursor

        data = _request(token, "GET", "/v1/users", logger, params=params)
        results = data.get("results", [])
        has_more = data.get("has_more", False)
        next_cursor = data.get("next_cursor")

        for item in results:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                if has_more and next_cursor:
                    resumable_source_manager.save_state(NotionResumeConfig(next_cursor=next_cursor))

        if not has_more or not next_cursor:
            break
        cursor = next_cursor

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def _iter_page_ids(token: str, logger: FilteringBoundLogger) -> Iterator[str]:
    cursor: str | None = None
    while True:
        data = _request(token, "POST", "/v1/search", logger, json_body=_search_body("page", cursor))
        for item in data.get("results", []):
            page_id = item.get("id")
            if page_id:
                yield page_id
        if not data.get("has_more") or not data.get("next_cursor"):
            break
        cursor = data["next_cursor"]


def _iter_block_children(
    token: str,
    block_id: str,
    page_id: str,
    logger: FilteringBoundLogger,
    depth: int,
) -> Iterator[dict[str, Any]]:
    cursor: str | None = None
    pages_fetched = 0
    while True:
        params: dict[str, Any] = {"page_size": NOTION_PAGE_SIZE}
        if cursor:
            params["start_cursor"] = cursor

        data = _request(token, "GET", f"/v1/blocks/{block_id}/children", logger, params=params)
        for block in data.get("results", []):
            block["_page_id"] = page_id
            yield block
            if block.get("has_children") and depth < MAX_BLOCK_DEPTH:
                yield from _iter_block_children(token, block["id"], page_id, logger, depth + 1)

        pages_fetched += 1
        if not data.get("has_more") or not data.get("next_cursor"):
            break
        if pages_fetched >= MAX_CHILD_PAGES_PER_PARENT:
            logger.warning(
                "Notion: reached block children page cap for parent",
                page_id=page_id,
                block_id=block_id,
                cap=MAX_CHILD_PAGES_PER_PARENT,
            )
            break
        cursor = data["next_cursor"]


def _blocks_stream(token: str, logger: FilteringBoundLogger) -> Iterator[Any]:
    batcher = Batcher(logger=logger, chunk_size=CHUNK_SIZE, chunk_size_bytes=CHUNK_SIZE_BYTES)

    for page_id in _iter_page_ids(token, logger):
        for block in _iter_block_children(token, page_id, page_id, logger, 0):
            batcher.batch(block)
            if batcher.should_yield():
                yield batcher.get_table()

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def _comments_stream(token: str, logger: FilteringBoundLogger) -> Iterator[Any]:
    batcher = Batcher(logger=logger, chunk_size=CHUNK_SIZE, chunk_size_bytes=CHUNK_SIZE_BYTES)

    for page_id in _iter_page_ids(token, logger):
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"block_id": page_id, "page_size": NOTION_PAGE_SIZE}
            if cursor:
                params["start_cursor"] = cursor

            data = _request(token, "GET", "/v1/comments", logger, params=params)
            for comment in data.get("results", []):
                comment["_page_id"] = page_id
                batcher.batch(comment)
                if batcher.should_yield():
                    yield batcher.get_table()

            if not data.get("has_more") or not data.get("next_cursor"):
                break
            cursor = data["next_cursor"]

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def get_rows(
    token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NotionResumeConfig],
) -> Iterator[Any]:
    config = NOTION_ENDPOINTS[endpoint]

    if config.stream_type == "search":
        yield from _search_stream(token, config, logger, resumable_source_manager)
    elif config.stream_type == "users":
        yield from _users_stream(token, logger, resumable_source_manager)
    elif config.stream_type == "blocks":
        yield from _blocks_stream(token, logger)
    elif config.stream_type == "comments":
        yield from _comments_stream(token, logger)
    else:
        raise ValueError(f"Unknown Notion stream type: {config.stream_type}")


def notion_source(
    token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NotionResumeConfig],
) -> SourceResponse:
    config = NOTION_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            token=token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
