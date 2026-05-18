import dataclasses
from datetime import UTC, date, datetime, time
from typing import Any, Optional

import requests
from dateutil import parser
from structlog.types import FilteringBoundLogger
from urllib3.util.retry import Retry

from posthog.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.paddle.settings import ENDPOINTS, INCREMENTAL_FIELDS

from products.data_warehouse.backend.models.external_table_definitions import get_dlt_mapping_for_external_table

PADDLE_BASE_URL = "https://api.paddle.com"


@dataclasses.dataclass
class PaddleResumeConfig:
    next_url: str


class PaddlePermissionError(Exception):
    pass


def _format_paddle_datetime_query_value(value: Any) -> str:
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


def _get_paddle_session() -> requests.Session:
    # Plain session with no retry adapter: errors fail fast so the caller
    # can surface them immediately rather than silently retrying.
    return make_tracked_session(retry=Retry(total=0))


def paddle_request(session: requests.Session, method: str, url: str, **kwargs) -> requests.Response:
    # No retry adapter on the session — errors surface immediately so the
    # caller (get_rows / validate_credentials) can decide how to handle them.
    response = session.request(method, url, **kwargs)
    return response


def get_rows(
    api_key: str,
    endpoint: str,
    db_incremental_field_last_value: Optional[Any],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PaddleResumeConfig],
    should_use_incremental_field: bool = False,
):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    url = f"{PADDLE_BASE_URL}/{endpoint}"
    params: dict[str, Any] = {"per_page": 200}
    incremental_field_config = INCREMENTAL_FIELDS.get(endpoint, [])
    incremental_field_name = incremental_field_config[0]["field"] if incremental_field_config else None

    params["order_by"] = f"{incremental_field_name}[ASC]" if incremental_field_name else "id[ASC]"

    if should_use_incremental_field and incremental_field_name:
        if db_incremental_field_last_value:
            params[f"{incremental_field_name}[GT]"] = _format_paddle_datetime_query_value(
                db_incremental_field_last_value
            )

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config and resume_config.next_url:
        url = resume_config.next_url
        params = {}

    batcher = Batcher(logger=logger)
    session = _get_paddle_session()
    seen_urls: set[str] = set()

    while url:
        if url in seen_urls:
            break
        seen_urls.add(url)

        response = paddle_request(session, "GET", url, headers=headers, params=params)

        response.raise_for_status()
        data = response.json()

        items = data.get("data", [])

        for item in items:
            batcher.batch(item)

            if batcher.should_yield():
                py_table = batcher.get_table()
                yield py_table

        meta = data.get("meta", {})
        pagination = meta.get("pagination", {})
        next_url = pagination.get("next")
        if next_url == url or next_url in seen_urls:
            next_url = None

        url = next_url
        params = {}

        if batcher.should_yield(include_incomplete_chunk=not url):
            py_table = batcher.get_table()
            if py_table.num_rows > 0:
                yield py_table

        if url:
            resumable_source_manager.save_state(PaddleResumeConfig(next_url=url))
        else:
            resumable_source_manager.save_state(PaddleResumeConfig(next_url=""))


def paddle_source(
    api_key: str,
    endpoint: str,
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PaddleResumeConfig],
) -> SourceResponse:
    column_mapping = get_dlt_mapping_for_external_table(f"paddle_{endpoint.lower()}")
    column_hints = {key: value.get("data_type") for key, value in column_mapping.items()}

    incremental_field_config = INCREMENTAL_FIELDS.get(endpoint, [])
    incremental_field_name = incremental_field_config[0]["field"] if incremental_field_config else None

    def items():
        yield from get_rows(
            api_key=api_key,
            endpoint=endpoint,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
            resumable_source_manager=resumable_source_manager,
            logger=logger,
        )

    return SourceResponse(
        items=items,
        primary_keys=["id"],
        name=endpoint,
        column_hints=column_hints,
        sort_mode="asc",
        partition_keys=[incremental_field_name] if incremental_field_name else None,
        partition_mode="datetime" if incremental_field_name else None,
        partition_count=1,
        partition_size=1,
        partition_format="week" if incremental_field_name else None,
    )


def validate_credentials(api_key: str, table_name: Optional[str] = None) -> bool:
    headers = {
        "Authorization": f"Bearer {api_key}",
    }

    endpoints_to_check = [table_name] if table_name else ENDPOINTS
    session = _get_paddle_session()

    for endpoint in endpoints_to_check:
        response = paddle_request(session, "GET", f"{PADDLE_BASE_URL}/{endpoint}", headers=headers)
        if response.status_code == 403:
            raise PaddlePermissionError(f"Missing permissions for {endpoint}")
        response.raise_for_status()

    return True
