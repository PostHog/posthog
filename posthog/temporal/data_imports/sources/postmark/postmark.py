from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

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


class PostmarkRetryableError(Exception):
    pass


def _get_headers(server_token: str) -> dict[str, str]:
    return {
        "X-Postmark-Server-Token": server_token,
        "Accept": "application/json",
    }


def _format_postmark_datetime(value: datetime) -> str:
    """Postmark accepts ISO-8601 datetimes without a timezone suffix; convert to UTC and drop tzinfo."""
    if value.tzinfo is None:
        utc_value = value.replace(tzinfo=UTC)
    else:
        utc_value = value.astimezone(UTC)
    return utc_value.replace(tzinfo=None).isoformat(timespec="seconds")


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
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if config.is_paginated:
        params["count"] = POSTMARK_PAGE_SIZE
        params["offset"] = offset
    if fromdate is not None:
        params["fromdate"] = _format_postmark_datetime(fromdate)
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


def get_rows(
    server_token: str,
    endpoint_name: str,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = POSTMARK_ENDPOINTS.get(endpoint_name)
    if config is None:
        raise ValueError(f"Unknown Postmark endpoint: {endpoint_name}")

    url = f"{POSTMARK_BASE_URL}{config.path}"
    fromdate = _resolve_fromdate(config, should_use_incremental_field, db_incremental_field_last_value, logger)

    session = make_tracked_session(headers=_get_headers(server_token))
    try:
        if not config.is_paginated:
            payload = _request(session, url, _build_params(config, offset=0, fromdate=fromdate), logger)
            items = payload.get(config.data_key, []) or []
            if items:
                yield items
            return

        offset = 0
        while True:
            params = _build_params(config, offset=offset, fromdate=fromdate)
            payload = _request(session, url, params, logger)
            items = payload.get(config.data_key, []) or []
            total_count = payload.get("TotalCount")

            if items:
                yield items

            offset += len(items)
            if not items or len(items) < POSTMARK_PAGE_SIZE:
                break
            if total_count is not None and offset >= total_count:
                break
    finally:
        session.close()


def validate_credentials(server_token: str) -> tuple[bool, Optional[str]]:
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
    if response.status_code == 403:
        return False, "Postmark Server API token is missing required permissions"
    if not response.ok:
        return False, f"Postmark API error: {response.status_code} {response.reason}"
    return True, None


def postmark_source(
    server_token: str,
    endpoint_name: str,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
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
            db_incremental_field_last_value=db_incremental_field_last_value,
        )

    return SourceResponse(
        name=endpoint_name,
        items=items,
        primary_keys=config.primary_key,
        partition_count=config.partition_count,
        partition_size=config.partition_size,
        partition_mode=config.partition_mode if config.partition_keys else None,
        partition_format=config.partition_format if config.partition_keys else None,
        partition_keys=config.partition_keys,
    )
