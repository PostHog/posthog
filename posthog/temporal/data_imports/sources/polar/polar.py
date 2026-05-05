import dataclasses
from datetime import UTC, date, datetime, time
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import requests
from dateutil import parser
from structlog.types import FilteringBoundLogger
from urllib3.util.retry import Retry

from posthog.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.polar.settings import ENDPOINTS, INCREMENTAL_FIELDS

POLAR_BASE_URL = "https://api.polar.sh"
PAGE_SIZE = 100


@dataclasses.dataclass
class PolarResumeConfig:
    next_url: str


class PolarPermissionError(Exception):
    pass


def _format_polar_datetime_query_value(value: Any) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min, tzinfo=UTC)
    else:
        parsed = parser.isoparse(str(value))

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    else:
        parsed = parsed.astimezone(UTC)

    return parsed.isoformat().replace("+00:00", "Z")


def _get_polar_session() -> requests.Session:
    # Plain session with no retry adapter: errors fail fast so the caller
    # can surface them immediately rather than silently retrying.
    return make_tracked_session(retry=Retry(total=0))


def polar_request(session: requests.Session, method: str, url: str, **kwargs) -> requests.Response:
    response = session.request(method, url, **kwargs)
    return response


def _default_sort_field(endpoint: str) -> str:
    config = INCREMENTAL_FIELDS.get(endpoint, [])
    return config[0]["field"] if config else "created_at"


def _build_url(endpoint: str, page: int, sort_field: str) -> str:
    prepared = requests.Request(
        "GET",
        f"{POLAR_BASE_URL}/v1/{endpoint}/",
        params={"limit": PAGE_SIZE, "page": page, "sorting": sort_field},
    ).prepare()
    return prepared.url or f"{POLAR_BASE_URL}/v1/{endpoint}/?limit={PAGE_SIZE}&page={page}&sorting={sort_field}"


def _page_from_url(url: str) -> int:
    qs = parse_qs(urlparse(url).query)
    page_values = qs.get("page", ["1"])
    try:
        return int(page_values[0])
    except (ValueError, IndexError):
        return 1


def get_rows(
    api_key: str,
    endpoint: str,
    incremental_field: Optional[str],
    db_incremental_field_last_value: Optional[Any],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PolarResumeConfig],
    should_use_incremental_field: bool = False,
):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }

    # Sort + cursor must use the same field. Prefer the user-configured incremental_field
    # so the URL's `sorting` param is consistent with the cutoff column we compare against.
    # When no incremental field is configured (full refresh), fall back to the endpoint's
    # default so subscriptions still gets `started_at` (created_at is rejected with 422).
    sort_field = incremental_field or _default_sort_field(endpoint)

    # Polar does not expose a server-side `<field>_gte` filter on every list endpoint, but
    # ascending sort lets us client-side skip rows whose timestamp is <= the last value the
    # pipeline saw. The pipeline itself dedupes on primary key, so this is just an
    # optimization to avoid re-yielding rows we already processed.
    cutoff: Optional[str] = None
    if should_use_incremental_field and incremental_field and db_incremental_field_last_value:
        cutoff = _format_polar_datetime_query_value(db_incremental_field_last_value)

    url: Optional[str] = _build_url(endpoint, page=1, sort_field=sort_field)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config and resume_config.next_url:
        url = resume_config.next_url

    batcher = Batcher(logger=logger)
    session = _get_polar_session()
    seen_urls: set[str] = set()

    while url:
        if url in seen_urls:
            break
        seen_urls.add(url)

        response = polar_request(session, "GET", url, headers=headers)
        response.raise_for_status()
        data = response.json()

        items = data.get("items", [])
        for item in items:
            if cutoff is not None and incremental_field:
                item_value = item.get(incremental_field)
                if item_value is not None and str(item_value) <= cutoff:
                    continue

            batcher.batch(item)

            if batcher.should_yield():
                yield batcher.get_table()

        pagination = data.get("pagination") or {}
        max_page = int(pagination.get("max_page") or 0)
        current_page = _page_from_url(url)

        if current_page < max_page:
            url = _build_url(endpoint, page=current_page + 1, sort_field=sort_field)
        else:
            url = None

        if batcher.should_yield(include_incomplete_chunk=not url):
            py_table = batcher.get_table()
            if py_table.num_rows > 0:
                yield py_table

        if url:
            resumable_source_manager.save_state(PolarResumeConfig(next_url=url))
        else:
            resumable_source_manager.save_state(PolarResumeConfig(next_url=""))


def polar_source(
    api_key: str,
    endpoint: str,
    incremental_field: Optional[str],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PolarResumeConfig],
) -> SourceResponse:
    def items():
        yield from get_rows(
            api_key=api_key,
            endpoint=endpoint,
            incremental_field=incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
            resumable_source_manager=resumable_source_manager,
            logger=logger,
        )

    return SourceResponse(
        items=items,
        primary_keys=["id"],
        name=endpoint,
        column_hints={},
        sort_mode="asc",
        partition_keys=[incremental_field] if incremental_field else None,
        partition_mode="datetime" if incremental_field else None,
        partition_count=1,
        partition_size=1,
        partition_format="month" if incremental_field else None,
    )


def validate_credentials(api_key: str, table_name: Optional[str] = None) -> bool:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }

    endpoints_to_check = [table_name] if table_name and table_name in ENDPOINTS else [ENDPOINTS[0]]
    session = _get_polar_session()

    for endpoint in endpoints_to_check:
        response = polar_request(
            session,
            "GET",
            f"{POLAR_BASE_URL}/v1/{endpoint}/",
            headers=headers,
            params={"limit": 1},
        )
        if response.status_code == 403:
            raise PolarPermissionError(f"Missing permissions for {endpoint}")
        response.raise_for_status()

    return True
