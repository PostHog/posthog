from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

import requests
from dateutil import parser
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.postmark.settings import (
    POSTMARK_BASE_URL,
    POSTMARK_ENDPOINTS,
    POSTMARK_PAGE_SIZE,
    PostmarkEndpointConfig,
)

# Postmark's `fromdate`/`todate` filters interpret timezone-naive ISO timestamps as the account's
# configured server timezone, and silently zero-result on inputs that include any explicit offset
# (`-04:00`, `Z`, etc.). The API does not expose the account's configured timezone, so:
#   - For datetimes that came from the pipeline (parsed from `received_at` rows that Postmark
#     itself returned), the original Postmark offset is already on the value — we preserve it and
#     just strip the tzinfo, so the wire format matches Postmark's expectation regardless of
#     whatever TZ the account is set to.
#   - For datetimes we generate internally (the default 30-day lookback on initial sync, when
#     there's no watermark), we have no signal and fall back to America/New_York (Postmark's
#     default for new accounts). Being off by a few hours on an initial 30-day backfill is benign.
POSTMARK_API_TIMEZONE_FALLBACK = ZoneInfo("America/New_York")

# Postmark documents `count + offset <= 10,000` for paginated message search endpoints. Past that
# the API returns ErrorCode 700 ("The combination of count and offset is too large"). We rotate
# the search window via `todate` instead of incrementing offset past this boundary.
POSTMARK_PAGINATION_CAP = 10_000

MESSAGE_STREAMS_PATH = "/message-streams"


class PostmarkRetryableError(Exception):
    pass


def _get_headers(server_token: str) -> dict[str, str]:
    return {
        "X-Postmark-Server-Token": server_token,
        "Accept": "application/json",
    }


def _format_postmark_datetime(value: datetime) -> str:
    """Format a datetime for Postmark's `fromdate`/`todate` filters.

    Postmark expects timezone-naive ISO-8601 strings interpreted in the account's configured
    server timezone, and silently zero-results on inputs with an explicit offset. The account's
    TZ is not exposed via API, so:
      - tz-aware inputs: keep their offset's wall-clock value and strip the offset. Watermarks
        coming from the pipeline carry Postmark's own offset (because that's how Postmark
        returned the `received_at` originally), so this works regardless of how the account is
        configured.
      - naive inputs (only the default lookback we generate ourselves): assume Eastern. Being
        off by a few hours on an initial 30-day backfill is benign.
    """
    if value.tzinfo is None:
        local_value = value.replace(tzinfo=UTC).astimezone(POSTMARK_API_TIMEZONE_FALLBACK)
        return local_value.replace(tzinfo=None).isoformat(timespec="seconds")
    return value.replace(tzinfo=None).isoformat(timespec="seconds")


def _parse_incremental_value(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return parser.parse(str(value))


def _resolve_fromdate(
    config: PostmarkEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    logger: FilteringBoundLogger,
    now: Optional[datetime] = None,
) -> Optional[datetime]:
    if config.incremental_field_api_name is None:
        return None

    current = now or datetime.now(UTC)
    last_value = _parse_incremental_value(db_incremental_field_last_value) if should_use_incremental_field else None

    if last_value is None and should_use_incremental_field:
        last_value = current - timedelta(days=config.default_lookback_days)

    if last_value is not None and config.max_window_days is not None:
        floor = current - timedelta(days=config.max_window_days)
        if last_value < floor:
            logger.warning(
                f"Postmark: requested fromdate {last_value.isoformat()} exceeds the {config.max_window_days}-day "
                f"search window for {config.path}; clamping to {floor.isoformat()}"
            )
            last_value = floor

    return last_value


def _build_params(
    config: PostmarkEndpointConfig,
    offset: int,
    fromdate: Optional[datetime],
    todate: Optional[datetime] = None,
    extra_params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if config.is_paginated:
        params["count"] = POSTMARK_PAGE_SIZE
        params["offset"] = offset
    if fromdate is not None:
        params["fromdate"] = _format_postmark_datetime(fromdate)
    if todate is not None:
        params["todate"] = _format_postmark_datetime(todate)
    if extra_params:
        params.update(extra_params)
    return params


def _request(session: requests.Session, url: str, params: dict[str, Any], logger: FilteringBoundLogger) -> dict:
    @retry(
        retry=retry_if_exception_type((PostmarkRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def _do() -> dict:
        response = session.get(url, params=params, timeout=60)

        if response.status_code == 429 or response.status_code >= 500:
            raise PostmarkRetryableError(f"Postmark API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Postmark API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    return _do()


def _paginate(
    session: requests.Session,
    url: str,
    config: PostmarkEndpointConfig,
    logger: FilteringBoundLogger,
    fromdate: Optional[datetime],
    todate: Optional[datetime],
    extra_params: Optional[dict[str, Any]] = None,
) -> Iterator[list[dict[str, Any]]]:
    if not config.is_paginated:
        payload = _request(
            session,
            url,
            _build_params(config, offset=0, fromdate=fromdate, todate=todate, extra_params=extra_params),
            logger,
        )
        items = payload.get(config.data_key, []) or []
        if items:
            yield items
        return

    cursor_field = config.incremental_field_api_name
    while True:
        offset = 0
        page_oldest_cursor: Optional[str] = None
        capped = False
        while True:
            # Postmark rejects requests where offset + count exceeds POSTMARK_PAGINATION_CAP.
            if offset + POSTMARK_PAGE_SIZE > POSTMARK_PAGINATION_CAP:
                capped = True
                break

            params = _build_params(config, offset=offset, fromdate=fromdate, todate=todate, extra_params=extra_params)
            payload = _request(session, url, params, logger)
            items = payload.get(config.data_key, []) or []
            total_count = payload.get("TotalCount")

            if items:
                yield items
                if cursor_field:
                    # Postmark sorts DESC by the cursor field, so the last item in the page has
                    # the lowest value seen so far in this window.
                    page_oldest_cursor = items[-1].get(cursor_field) or page_oldest_cursor

            offset += len(items)
            if not items or len(items) < POSTMARK_PAGE_SIZE:
                return
            if total_count is not None and offset >= total_count:
                return

        # We hit the offset+count cap inside this window. Rotate the upper bound to the oldest
        # cursor we saw in this window and reset offset. PK-merge handles boundary re-fetches in
        # incremental mode; append accepts the duplicates as it does for normal boundary overlap.
        if not capped or cursor_field is None or page_oldest_cursor is None:
            logger.warning(
                f"Postmark: hit {POSTMARK_PAGINATION_CAP}-row pagination cap on {url} without a cursor to rotate; "
                f"truncating remaining rows. Re-run after the watermark advances."
            )
            return
        new_todate = parser.parse(page_oldest_cursor)
        if todate is not None and new_todate >= todate:
            logger.warning(
                f"Postmark: pagination window rotation on {url} not advancing past {todate.isoformat()}; truncating."
            )
            return
        todate = new_todate


def _list_message_stream_ids(session: requests.Session, logger: FilteringBoundLogger) -> list[str]:
    payload = _request(session, f"{POSTMARK_BASE_URL}{MESSAGE_STREAMS_PATH}", {}, logger)
    return [s["ID"] for s in payload.get("MessageStreams", []) if "ID" in s]


def _fan_out_targets(
    config: PostmarkEndpointConfig, stream_ids: list[str]
) -> Iterator[tuple[str, str, dict[str, Any], bool]]:
    """Yield (stream_id, url, extra_params, enrich) tuples for fan-out endpoints.

    Two fan-out modes:
      - path substitution (`{stream_id}` in path) — used by `suppressions`. The dump endpoint's
        rows don't include the stream id, so we enrich each row with `MessageStreamID`.
      - query-param (`?messagestream=`) — used by outbound message search endpoints. Their
        responses already include a `MessageStream` field, so no enrichment is needed.
    """
    for stream_id in stream_ids:
        if "{stream_id}" in config.path:
            yield stream_id, f"{POSTMARK_BASE_URL}{config.path.format(stream_id=stream_id)}", {}, True
        else:
            yield stream_id, f"{POSTMARK_BASE_URL}{config.path}", {"messagestream": stream_id}, False


def _yield_for_target(
    session: requests.Session,
    config: PostmarkEndpointConfig,
    logger: FilteringBoundLogger,
    url: str,
    extra_params: dict[str, Any],
    stream_id: Optional[str],
    enrich: bool,
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
    db_incremental_field_last_value: Any,
    db_incremental_field_earliest_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Run the full-refresh or two-phase incremental flow for one (url, extra_params) pair."""

    def emit(chunk: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if enrich and stream_id is not None:
            return [{**row, "MessageStreamID": stream_id} for row in chunk]
        return chunk

    api_field_name = incremental_field or config.incremental_field_api_name
    if not should_use_incremental_field or api_field_name is None:
        for chunk in _paginate(session, url, config, logger, fromdate=None, todate=None, extra_params=extra_params):
            yield emit(chunk)
        return

    # Postmark list endpoints return rows DESC by their time column with no `sorting=` param to
    # flip that, so SourceResponse.sort_mode is "desc". Mirror Stripe's two-phase incremental:
    # backfill rows older than the earliest watermark first, then catch up rows newer than the
    # last watermark.
    now = datetime.now(UTC)
    earliest = _parse_incremental_value(db_incremental_field_earliest_value)
    if earliest is not None:
        window_floor = now - timedelta(days=config.max_window_days) if config.max_window_days is not None else None
        if window_floor is not None and earliest <= window_floor:
            logger.debug(
                f"Postmark: skipping backfill for {config.path}; earliest watermark {earliest.isoformat()} "
                f"is at or before the {config.max_window_days}-day search window"
            )
        else:
            for chunk in _paginate(
                session, url, config, logger, fromdate=None, todate=earliest, extra_params=extra_params
            ):
                yield emit(chunk)

    fromdate = _resolve_fromdate(
        config,
        should_use_incremental_field=True,
        db_incremental_field_last_value=db_incremental_field_last_value,
        logger=logger,
        now=now,
    )
    for chunk in _paginate(session, url, config, logger, fromdate=fromdate, todate=None, extra_params=extra_params):
        yield emit(chunk)


def get_rows(
    server_token: str,
    endpoint_name: str,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    incremental_field: Optional[str] = None,
    db_incremental_field_last_value: Any = None,
    db_incremental_field_earliest_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = POSTMARK_ENDPOINTS.get(endpoint_name)
    if config is None:
        raise ValueError(f"Unknown Postmark endpoint: {endpoint_name}")

    session = make_tracked_session(headers=_get_headers(server_token))
    try:
        if config.fan_out_streams:
            stream_ids = _list_message_stream_ids(session, logger)
            if not stream_ids:
                logger.debug(f"Postmark: no message streams found, skipping {config.path}")
                return
            for stream_id, url, extra_params, enrich in _fan_out_targets(config, stream_ids):
                yield from _yield_for_target(
                    session,
                    config,
                    logger,
                    url=url,
                    extra_params=extra_params,
                    stream_id=stream_id,
                    enrich=enrich,
                    should_use_incremental_field=should_use_incremental_field,
                    incremental_field=incremental_field,
                    db_incremental_field_last_value=db_incremental_field_last_value,
                    db_incremental_field_earliest_value=db_incremental_field_earliest_value,
                )
            return

        yield from _yield_for_target(
            session,
            config,
            logger,
            url=f"{POSTMARK_BASE_URL}{config.path}",
            extra_params={},
            stream_id=None,
            enrich=False,
            should_use_incremental_field=should_use_incremental_field,
            incremental_field=incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            db_incremental_field_earliest_value=db_incremental_field_earliest_value,
        )
    finally:
        session.close()


def validate_credentials(server_token: str, schema_name: Optional[str] = None) -> tuple[bool, Optional[str]]:
    if not server_token:
        return False, "Postmark Server API token is required"

    try:
        session = make_tracked_session(headers=_get_headers(server_token))
        try:
            response = session.get(f"{POSTMARK_BASE_URL}/server", timeout=10)
        finally:
            session.close()
    except Exception as exc:
        return False, f"Could not reach Postmark API: {exc}"

    if response.status_code == 401:
        return False, "Invalid Postmark Server API token"
    # At source-create (schema_name is None) we accept 403: a token can legitimately be valid but
    # scoped to fewer endpoints than the full schema set. Re-raise 403 only when probing for a
    # specific schema, where the user explicitly asked whether that endpoint will work.
    if response.status_code == 403:
        if schema_name is None:
            return True, None
        return False, "Postmark Server API token is missing required permissions"
    if not response.ok:
        return False, f"Postmark API error: {response.status_code} {response.reason}"
    return True, None


def postmark_source(
    server_token: str,
    endpoint_name: str,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    incremental_field: Optional[str] = None,
    db_incremental_field_last_value: Any = None,
    db_incremental_field_earliest_value: Any = None,
) -> SourceResponse:
    config = POSTMARK_ENDPOINTS.get(endpoint_name)
    if config is None:
        raise ValueError(f"Unknown Postmark endpoint: {endpoint_name}")

    def items() -> Iterator[list[dict[str, Any]]]:
        yield from get_rows(
            server_token=server_token,
            endpoint_name=endpoint_name,
            logger=logger,
            should_use_incremental_field=should_use_incremental_field,
            incremental_field=incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            db_incremental_field_earliest_value=db_incremental_field_earliest_value,
        )

    # Postmark list endpoints return rows DESC by their time column and offer no `sorting=` to
    # flip that, so incremental endpoints declare sort_mode="desc" and rely on the pipeline
    # passing both the earliest and latest watermarks for two-phase paging.
    sort_mode = "desc" if config.incremental_field_api_name is not None else "asc"

    return SourceResponse(
        name=endpoint_name,
        items=items,
        primary_keys=config.primary_key,
        partition_count=config.partition_count,
        partition_size=config.partition_size,
        partition_mode=config.partition_mode if config.partition_keys else None,
        partition_format=config.partition_format if config.partition_keys else None,
        partition_keys=config.partition_keys,
        sort_mode=sort_mode,
    )
