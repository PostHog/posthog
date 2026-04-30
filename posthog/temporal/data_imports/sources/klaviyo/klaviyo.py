import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.klaviyo.settings import KLAVIYO_ENDPOINTS, KlaviyoEndpointConfig

KLAVIYO_BASE_URL = "https://a.klaviyo.com/api"


class KlaviyoRetryableError(Exception):
    pass


@dataclasses.dataclass
class KlaviyoResumeConfig:
    next_url: str


def _format_datetime_z(dt: datetime) -> str:
    """Format a datetime as ISO 8601 with Z suffix, which Klaviyo's API requires.

    Klaviyo rejects the +00:00 UTC offset format produced by isoformat(),
    so we must use the Z suffix instead.
    """
    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _format_incremental_value(value: Any) -> str:
    """Format incremental field value for Klaviyo API filters."""
    if isinstance(value, datetime):
        return _format_datetime_z(value)
    if isinstance(value, date):
        return _format_datetime_z(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


def _build_filter(
    config: KlaviyoEndpointConfig,
    incremental_field: str | None,
    formatted_value: str | None,
) -> str | None:
    """Build Klaviyo filter string from config."""
    filter_field = incremental_field or config.default_incremental_field
    incremental_filter = f"greater-than({filter_field},{formatted_value})" if formatted_value else None

    if config.base_filter and incremental_filter:
        return f"and({config.base_filter},{incremental_filter})"
    elif config.base_filter:
        return config.base_filter
    else:
        return incremental_filter


def _build_url(base_url: str, params: dict[str, Any]) -> str:
    """Build a URL with query params without percent-encoding.

    Klaviyo's API expects literal brackets, parentheses, and quotes in query params
    (e.g. page[size]=100, filter=equals(messages.channel,'email')).
    All param keys and values are constructed internally, so no encoding is needed.
    """
    if not params:
        return base_url
    parts = [f"{key}={value}" for key, value in params.items()]
    return f"{base_url}?{'&'.join(parts)}"


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Klaviyo-API-Key {api_key}",
        "revision": "2024-10-15",
        "Accept": "application/json",
    }


def validate_credentials(api_key: str) -> bool:
    url = f"{KLAVIYO_BASE_URL}/accounts"
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _flatten_item(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten the 'attributes' object into the root level for a single item."""
    if "attributes" in item and isinstance(item["attributes"], dict):
        attributes = item.pop("attributes")
        item.update(attributes)
    return item


def _build_initial_params(
    config: KlaviyoEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    """Build query params for the initial Klaviyo API request."""
    params: dict[str, Any] = {}

    if config.page_size is not None and config.page_size > 0:
        params["page[size]"] = config.page_size

    # On first sync/full refresh, apply a lookback window to avoid fetching the entire history
    if should_use_incremental_field and not db_incremental_field_last_value and config.default_lookback_days:
        db_incremental_field_last_value = datetime.now(UTC) - timedelta(days=config.default_lookback_days)

    formatted_last_value = (
        _format_incremental_value(db_incremental_field_last_value)
        if should_use_incremental_field and db_incremental_field_last_value
        else None
    )
    filter_value = _build_filter(config, incremental_field, formatted_last_value)
    if filter_value:
        params["filter"] = filter_value

    if config.sort:
        params["sort"] = config.sort

    return params


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[KlaviyoResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = KLAVIYO_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)

    params = _build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    # Check for resume state
    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if resume_config is not None:
        url = resume_config.next_url
        logger.debug(f"Klaviyo: resuming from URL: {url}")
    else:
        url = _build_url(f"{KLAVIYO_BASE_URL}{config.path}", params)

    @retry(
        retry=retry_if_exception_type((KlaviyoRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict:
        response = make_tracked_session().get(page_url, headers=headers, timeout=60)

        if response.status_code == 429 or response.status_code >= 500:
            raise KlaviyoRetryableError(f"Klaviyo API error (retryable): status={response.status_code}, url={page_url}")

        if not response.ok:
            logger.error(f"Klaviyo API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(url)

        items = data.get("data", [])
        if not items:
            break

        # Get next page URL before iterating items
        links = data.get("links", {})
        next_url = links.get("next")

        for item in items:
            batcher.batch(_flatten_item(item))

            if batcher.should_yield():
                py_table = batcher.get_table()
                yield py_table

                if next_url:
                    resumable_source_manager.save_state(KlaviyoResumeConfig(next_url=next_url))

        if not next_url:
            break

        url = next_url

    if batcher.should_yield(include_incomplete_chunk=True):
        py_table = batcher.get_table()
        yield py_table


def klaviyo_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[KlaviyoResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = KLAVIYO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
