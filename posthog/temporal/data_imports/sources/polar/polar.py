import dataclasses
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from urllib3.util.retry import Retry

from posthog.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.polar.settings import ENDPOINT_SORT_FIELDS, ENDPOINTS

POLAR_BASE_URL = "https://api.polar.sh"
PAGE_SIZE = 100


@dataclasses.dataclass
class PolarResumeConfig:
    next_url: str


class PolarPermissionError(Exception):
    pass


def _get_polar_session() -> requests.Session:
    # Plain session with no retry adapter: errors fail fast so the caller
    # can surface them immediately rather than silently retrying.
    return make_tracked_session(retry=Retry(total=0))


def polar_request(session: requests.Session, method: str, url: str, **kwargs) -> requests.Response:
    response = session.request(method, url, **kwargs)
    return response


def _build_url(endpoint: str, page: int) -> str:
    params: dict[str, str | int] = {"limit": PAGE_SIZE, "page": page}
    sort_field = ENDPOINT_SORT_FIELDS.get(endpoint)
    if sort_field is not None:
        params["sorting"] = sort_field
    return f"{POLAR_BASE_URL}/v1/{endpoint}/?{urlencode(params)}"


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
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PolarResumeConfig],
):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }

    url: Optional[str] = _build_url(endpoint, page=1)

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
            batcher.batch(item)

            if batcher.should_yield():
                yield batcher.get_table()

        pagination = data.get("pagination") or {}
        max_page = int(pagination.get("max_page") or 0)
        current_page = _page_from_url(url)

        if current_page < max_page:
            url = _build_url(endpoint, page=current_page + 1)
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
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PolarResumeConfig],
) -> SourceResponse:
    def items():
        yield from get_rows(
            api_key=api_key,
            endpoint=endpoint,
            resumable_source_manager=resumable_source_manager,
            logger=logger,
        )

    return SourceResponse(
        items=items,
        primary_keys=["id"],
        name=endpoint,
        column_hints={},
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
