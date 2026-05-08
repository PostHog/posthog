# TODO(warehouse): migrate to RESTAPIConfig once `JSONBodyCursorPaginator` lands in the shared rest_source paginators.

import dataclasses
from collections.abc import Generator
from datetime import datetime
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.notion.settings import (
    DATA_SOURCE_ROWS_PREFIX,
    LAST_EDITED_TIME,
    NOTION_API_URL,
    NOTION_API_VERSION,
    NOTION_DEFAULT_PAGE_SIZE,
    NOTION_STATIC_ENDPOINTS,
    data_source_rows_endpoint_config,
)


class NotionRetryableError(Exception):
    pass


@dataclasses.dataclass
class NotionResumeConfig:
    cursor: str


def _make_session(access_token: str) -> requests.Session:
    return make_tracked_session(
        headers={
            "Authorization": f"Bearer {access_token}",
            "Notion-Version": NOTION_API_VERSION,
            "Content-Type": "application/json",
        }
    )


def _execute_get(sess: requests.Session, url: str, params: dict[str, Any]) -> dict[str, Any]:
    @retry(
        retry=retry_if_exception_type(NotionRetryableError),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def _do() -> dict[str, Any]:
        response = sess.get(url, params=params, timeout=60)
        if response.status_code >= 500 or response.status_code == 429:
            raise NotionRetryableError(f"Notion: server/rate-limit error {response.status_code}")
        try:
            payload = response.json()
        except Exception:
            if not response.ok:
                raise Exception(f"{response.status_code} Client Error: {response.reason} (Notion API: {response.text})")
            raise Exception(f"Unexpected Notion response: {response.text}")
        if not response.ok:
            message = payload.get("message") or response.reason
            raise Exception(f"{response.status_code} Client Error: {message} (Notion API)")
        return payload

    return _do()


def _execute_post(sess: requests.Session, url: str, json_body: dict[str, Any] | None) -> dict[str, Any]:
    @retry(
        retry=retry_if_exception_type(NotionRetryableError),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def _do() -> dict[str, Any]:
        response = sess.post(url, json=json_body, timeout=60)

        if response.status_code >= 500 or response.status_code == 429:
            raise NotionRetryableError(f"Notion: server/rate-limit error {response.status_code}")

        try:
            payload = response.json()
        except Exception:
            if not response.ok:
                raise Exception(f"{response.status_code} Client Error: {response.reason} (Notion API: {response.text})")
            raise Exception(f"Unexpected Notion response: {response.text}")

        if not response.ok:
            message = payload.get("message") or response.reason
            raise Exception(f"{response.status_code} Client Error: {message} (Notion API)")

        return payload

    return _do()


def _paginate(
    sess: requests.Session,
    method: str,
    url: str,
    body: dict[str, Any] | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NotionResumeConfig],
    incremental_filter: dict[str, Any] | None = None,
) -> Generator[list[dict[str, Any]], None, None]:
    """Cursor-paginate a Notion endpoint that uses `start_cursor` / `next_cursor` / `has_more`.

    Notion's POST endpoints (`/search`, `/data_sources/{id}/query`) accept the cursor and
    page_size in the JSON body. The GET `/users` endpoint accepts them as query params,
    so for those we pass `body=None` and the caller adds the params to `url`.
    """
    request_body: dict[str, Any] = dict(body) if body else {}
    request_body["page_size"] = NOTION_DEFAULT_PAGE_SIZE
    if incremental_filter is not None:
        # `/data_sources/{id}/query` accepts a `filter` field — let the caller wire it in.
        request_body["filter"] = incremental_filter

    resume_config = resumable_source_manager.load_state()
    if resume_config is not None:
        request_body["start_cursor"] = resume_config.cursor
        logger.debug(f"Notion: resuming from saved cursor on {url}")

    while True:
        if method == "GET":
            # GET /v1/users uses query params, not a JSON body.
            params = {k: v for k, v in request_body.items() if v is not None}
            payload = _execute_get(sess, url, params)
        else:
            payload = _execute_post(sess, url, request_body)

        results = payload.get("results", [])
        yield results

        if not payload.get("has_more"):
            break

        next_cursor = payload.get("next_cursor")
        if not next_cursor:
            # `has_more=True` with a missing/null next_cursor would loop forever — fail loudly.
            raise Exception(f"Notion: has_more=True but next_cursor is empty for {url}")

        request_body["start_cursor"] = next_cursor
        # Checkpoint after yielding the batch: on resume the first request re-fetches that page;
        # full-refresh appends and incremental merges on the primary key, so duplicates are tolerated.
        resumable_source_manager.save_state(NotionResumeConfig(cursor=next_cursor))


# ---------------------------------------------------------------------------
# Notion property flattening for data source rows
# ---------------------------------------------------------------------------


# A small set of Notion property types we extract into a stable scalar/string column.
# Anything we don't recognize falls through and is preserved in `_raw_properties`.
def _flatten_property(prop: dict[str, Any]) -> Any:
    ptype = prop.get("type")
    if ptype is None:
        return None

    value = prop.get(ptype)
    if value is None:
        return None

    if ptype in ("title", "rich_text"):
        # value is a list of rich text spans — concatenate plain_text for a flat string.
        if isinstance(value, list):
            return "".join(span.get("plain_text", "") for span in value)
        return None
    if ptype == "number":
        return value
    if ptype in ("select", "status"):
        return value.get("name") if isinstance(value, dict) else None
    if ptype == "multi_select":
        return [opt.get("name") for opt in value] if isinstance(value, list) else None
    if ptype == "date":
        if isinstance(value, dict):
            return value.get("start")
        return None
    if ptype == "checkbox":
        return bool(value)
    if ptype in ("url", "email", "phone_number"):
        return value
    if ptype == "people":
        return [p.get("id") for p in value] if isinstance(value, list) else None
    if ptype == "relation":
        return [r.get("id") for r in value] if isinstance(value, list) else None
    if ptype == "files":
        return (
            [f.get("file", {}).get("url") or f.get("external", {}).get("url") for f in value]
            if isinstance(value, list)
            else None
        )
    if ptype == "created_by":
        return value.get("id") if isinstance(value, dict) else None
    if ptype == "last_edited_by":
        return value.get("id") if isinstance(value, dict) else None
    if ptype in ("created_time", "last_edited_time"):
        return value
    if ptype == "formula":
        # Formulas wrap an inner type — recurse via the same flattener.
        return _flatten_property({"type": value.get("type"), value.get("type"): value.get(value.get("type"))})
    if ptype == "rollup":
        return value  # leave as-is in the typed column; raw lives in _raw_properties anyway
    # Unknown / unsupported property type — keep null in the typed column; raw is preserved.
    return None


# Top-level keys we always emit per row. A user-defined Notion property with one of
# these names would silently overwrite the value (most critically `id`, the merge
# primary key — a property called "id" with a numeric value would corrupt every
# subsequent merge). Notion users do create properties with these names, so we keep
# the structural value at the top level and surface the user property only via the
# untouched `_raw_properties` payload.
_RESERVED_FLATTENED_KEYS = frozenset(
    {"id", "object", "created_time", "last_edited_time", "archived", "url", "parent", "_raw_properties"}
)


def _flatten_row(row: dict[str, Any]) -> dict[str, Any]:
    properties = row.get("properties") or {}
    # `id` is the merge primary key — fail fast if Notion ever returns a row without
    # it instead of silently producing a None-keyed row that corrupts the merge.
    flattened: dict[str, Any] = {
        "id": row["id"],
        "object": row.get("object"),
        "created_time": row.get("created_time"),
        "last_edited_time": row.get("last_edited_time"),
        "archived": row.get("archived"),
        "url": row.get("url"),
        "parent": row.get("parent"),
        "_raw_properties": properties,
    }
    for prop_name, prop_value in properties.items():
        if prop_name in _RESERVED_FLATTENED_KEYS:
            continue
        if isinstance(prop_value, dict):
            flattened[prop_name] = _flatten_property(prop_value)
    return flattened


# ---------------------------------------------------------------------------
# Endpoint fetchers
# ---------------------------------------------------------------------------


def _fetch_users(
    sess: requests.Session,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NotionResumeConfig],
) -> Generator[list[dict[str, Any]], None, None]:
    yield from _paginate(
        sess=sess,
        method="GET",
        url=f"{NOTION_API_URL}/users",
        body=None,
        logger=logger,
        resumable_source_manager=resumable_source_manager,
    )


def _fetch_search(
    sess: requests.Session,
    object_filter: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NotionResumeConfig],
    last_edited_gte: str | None,
    incremental_field: str,
) -> Generator[list[dict[str, Any]], None, None]:
    body: dict[str, Any] = {"filter": {"property": "object", "value": object_filter}}
    for batch in _paginate(
        sess=sess,
        method="POST",
        url=f"{NOTION_API_URL}/search",
        body=body,
        logger=logger,
        resumable_source_manager=resumable_source_manager,
    ):
        # `/search` does not support server-side time filtering, so we filter client-side
        # using whichever timestamp field the user picked as the incremental cursor.
        if last_edited_gte is None:
            yield batch
        else:
            yield [item for item in batch if (item.get(incremental_field) or "") > last_edited_gte]


def _fetch_data_source_rows(
    sess: requests.Session,
    data_source_id: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NotionResumeConfig],
    last_edited_gte: str | None,
    incremental_field: str,
) -> Generator[list[dict[str, Any]], None, None]:
    incremental_filter: dict[str, Any] | None = None
    if last_edited_gte is not None:
        # `/data_sources/{id}/query` supports server-side filtering on the row timestamp
        # the user picked as the incremental cursor (Notion accepts created_time or
        # last_edited_time here).
        incremental_filter = {
            "timestamp": incremental_field,
            incremental_field: {"after": last_edited_gte},
        }

    for batch in _paginate(
        sess=sess,
        method="POST",
        url=f"{NOTION_API_URL}/data_sources/{data_source_id}/query",
        body=None,
        logger=logger,
        resumable_source_manager=resumable_source_manager,
        incremental_filter=incremental_filter,
    ):
        yield [_flatten_row(row) for row in batch]


def _extract_title(item: dict[str, Any]) -> str | None:
    """Concatenate the plain_text of a Notion `title` rich-text array. Returns None if empty."""
    title = item.get("title")
    if not isinstance(title, list):
        return None
    text = "".join(span.get("plain_text", "") for span in title if isinstance(span, dict))
    return text or None


def _list_data_sources(
    access_token: str,
    ids: list[str] | None = None,
) -> list[tuple[str, str | None]]:
    """Returns (id, title) for the requested data sources, or all of them when `ids` is None.

    Each Notion database can host one or more data sources (the queryable row collections).
    With `ids` we issue one `GET /v1/data_sources/{id}` per requested id — cheap for small
    lookups (e.g. the `incremental_fields` API endpoint, which always passes a single id).
    Without `ids` we paginate `/v1/search?filter=data_source` over the whole workspace —
    cheaper than per-id when discovering everything for the first time.
    """
    sess = _make_session(access_token)
    try:
        if ids is not None:
            results: list[tuple[str, str | None]] = []
            for ds_id in ids:
                response = sess.get(f"{NOTION_API_URL}/data_sources/{ds_id}", timeout=30)
                response.raise_for_status()
                payload = response.json()
                results.append((payload["id"], _extract_title(payload)))
            return results

        data_sources: list[tuple[str, str | None]] = []
        body: dict[str, Any] = {
            "filter": {"property": "object", "value": "data_source"},
            "page_size": NOTION_DEFAULT_PAGE_SIZE,
        }
        while True:
            response = sess.post(f"{NOTION_API_URL}/search", json=body, timeout=30)
            response.raise_for_status()
            payload = response.json()
            for item in payload.get("results", []):
                ds_id = item.get("id")
                if ds_id:
                    data_sources.append((ds_id, _extract_title(item)))
            if not payload.get("has_more"):
                return data_sources
            next_cursor = payload.get("next_cursor")
            if not next_cursor:
                # Mirror `_paginate`'s behavior — silently returning here would hide an
                # incomplete enumeration and users would see fewer data sources than exist.
                raise Exception(f"Notion: has_more=True but next_cursor is empty for {NOTION_API_URL}/search")
            body["start_cursor"] = next_cursor
    finally:
        sess.close()


# ---------------------------------------------------------------------------
# Top-level dispatch
# ---------------------------------------------------------------------------


def notion_source(
    access_token: str,
    endpoint_name: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NotionResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any | None = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    """Build a SourceResponse for a single Notion endpoint or per-data-source row table."""
    is_ds_rows = endpoint_name.startswith(DATA_SOURCE_ROWS_PREFIX)

    if is_ds_rows:
        endpoint_config = data_source_rows_endpoint_config()
    else:
        endpoint_config = NOTION_STATIC_ENDPOINTS.get(endpoint_name)  # type: ignore[assignment]
        if endpoint_config is None:
            raise ValueError(f"Unknown Notion endpoint: {endpoint_name}")

    last_edited_gte: str | None = None
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        # Datetime cursors must be ISO 8601 (T-separated) — both for Notion's API filter
        # and for the client-side string comparison against Notion's response timestamps
        # (which use the `T` separator). `str(datetime)` would produce a space-separated
        # form that mis-orders lexicographically vs. response values from the same day.
        if isinstance(db_incremental_field_last_value, datetime):
            last_edited_gte = db_incremental_field_last_value.isoformat()
        else:
            last_edited_gte = str(db_incremental_field_last_value)
        logger.debug(f"Notion: incremental sync for {endpoint_name} since {last_edited_gte}")

    # Fall back to `last_edited_time` when the caller doesn't tell us which field the user
    # picked. That's also the only entry currently in `INCREMENTAL_DATETIME_FIELDS`, so the
    # fallback matches today's UI in practice — but if anyone extends that list, this code
    # honors whatever field the user actually selected without further changes.
    field = incremental_field or LAST_EDITED_TIME

    def get_rows() -> Generator[list[dict[str, Any]], None, None]:
        sess = _make_session(access_token)
        try:
            if endpoint_name == "users":
                yield from _fetch_users(sess, logger, resumable_source_manager)
            elif endpoint_name == "pages":
                yield from _fetch_search(sess, "page", logger, resumable_source_manager, last_edited_gte, field)
            elif endpoint_name == "data_sources":
                yield from _fetch_search(sess, "data_source", logger, resumable_source_manager, last_edited_gte, field)
            elif is_ds_rows:
                # Reverse the schema_name → data_source_id mapping. `data_source_rows__<hex32>`
                # only encodes the hyphenless ID; Notion accepts both hyphenated and hyphenless IDs.
                data_source_id = endpoint_name[len(DATA_SOURCE_ROWS_PREFIX) :]
                yield from _fetch_data_source_rows(
                    sess, data_source_id, logger, resumable_source_manager, last_edited_gte, field
                )
            else:
                raise ValueError(f"Unknown Notion endpoint: {endpoint_name}")
        finally:
            sess.close()

    return SourceResponse(
        items=get_rows,
        primary_keys=[endpoint_config.primary_key],
        name=endpoint_name,
        partition_count=endpoint_config.partition_count,
        partition_size=endpoint_config.partition_size,
        partition_mode=endpoint_config.partition_mode,
        partition_format=endpoint_config.partition_format,
        partition_keys=endpoint_config.partition_keys,
    )


def validate_credentials(access_token: str) -> tuple[bool, str | None]:
    try:
        sess = _make_session(access_token)
        try:
            response = sess.get(f"{NOTION_API_URL}/users/me", timeout=10)
            if response.status_code == 200:
                return True, None
            try:
                payload = response.json()
                message = payload.get("message") or response.reason
            except Exception:
                message = response.reason
            return False, f"Notion API error ({response.status_code}): {message}"
        finally:
            sess.close()
    except Exception as e:
        return False, str(e)
