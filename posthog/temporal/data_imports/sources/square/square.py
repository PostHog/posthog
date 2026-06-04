import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.square.settings import SQUARE_ENDPOINTS, SquareEndpointConfig

# Square pins API behaviour to a dated version header. Bump deliberately after
# re-reading the changelog — newer versions can reshape responses.
SQUARE_API_VERSION = "2024-10-17"

SQUARE_HOSTS = {
    "production": "https://connect.squareup.com",
    "sandbox": "https://connect.squareupsandbox.com",
}

PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60


class SquareRetryableError(Exception):
    pass


@dataclasses.dataclass
class SquareResumeConfig:
    # The next-page pagination cursor returned by Square. Square cursors expire
    # after ~5 minutes, so a resume that lands outside that window will re-fetch
    # the stream from the start (merge dedupes on the primary key).
    cursor: str


def _base_url(environment: str) -> str:
    return SQUARE_HOSTS.get(environment, SQUARE_HOSTS["production"])


def _get_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Square-Version": SQUARE_API_VERSION,
        "Accept": "application/json",
    }


def _format_rfc3339(value: Any) -> str:
    """Format an incremental value as the RFC 3339 timestamp Square expects."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return str(value)


def _build_initial_params(
    config: SquareEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, str]:
    params: dict[str, str] = dict(config.extra_params)

    if config.paginated:
        params["limit"] = str(PAGE_SIZE)

    if config.time_filter_param and should_use_incremental_field and db_incremental_field_last_value is not None:
        params[config.time_filter_param] = _format_rfc3339(db_incremental_field_last_value)

    return params


def validate_credentials(access_token: str, environment: str, schema_name: Optional[str] = None) -> tuple[bool, bool]:
    """Probe Square to confirm the token works.

    Returns ``(is_valid, is_forbidden)``. ``is_forbidden`` distinguishes a 403
    (valid token, missing scope) from a 401 (bad token) so the caller can accept
    scope gaps at source-create time but reject them for a specific schema.
    """
    config = SQUARE_ENDPOINTS.get(schema_name) if schema_name else None
    path = config.path if config else "/v2/locations"

    # Keep the probe cheap on paginated endpoints, but never send `limit` to a
    # non-paginated endpoint (e.g. /v2/locations) — Square may reject the unknown param.
    params: dict[str, str] = {}
    if config is not None and config.paginated:
        params["limit"] = "1"

    url = f"{_base_url(environment)}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"

    try:
        response = make_tracked_session().get(url, headers=_get_headers(access_token), timeout=REQUEST_TIMEOUT_SECONDS)
    except Exception:
        return False, False

    if response.status_code == 403:
        return False, True

    return response.status_code == 200, False


def get_rows(
    access_token: str,
    environment: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SquareResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = SQUARE_ENDPOINTS[endpoint]
    headers = _get_headers(access_token)
    url = f"{_base_url(environment)}{config.path}"

    initial_params = _build_initial_params(config, should_use_incremental_field, db_incremental_field_last_value)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor: Optional[str] = resume_config.cursor if resume_config else None
    if cursor:
        logger.debug(f"Square: resuming {endpoint} from saved cursor")

    @retry(
        retry=retry_if_exception_type((SquareRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(params: dict[str, str]) -> dict[str, Any]:
        response = make_tracked_session().get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise SquareRetryableError(f"Square API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Square API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    while True:
        # Square encodes the original query in the cursor, so subsequent pages are
        # requested with the cursor alone — re-sending filters/sort can error.
        params = {"cursor": cursor} if cursor else initial_params
        data = fetch_page(params)

        items = data.get(config.data_key, [])
        next_cursor = data.get("cursor")

        if items:
            yield items
            # Save state only after yielding, so a crash re-yields the last batch
            # rather than skipping it (merge dedupes on the primary key). No point
            # persisting a cursor for non-paginated endpoints — there's nothing to
            # resume into.
            if config.paginated and next_cursor:
                resumable_source_manager.save_state(SquareResumeConfig(cursor=next_cursor))

        if not config.paginated or not next_cursor:
            break

        cursor = next_cursor


def square_source(
    access_token: str,
    environment: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SquareResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SQUARE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_token=access_token,
            environment=environment,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
