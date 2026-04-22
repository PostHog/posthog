import dataclasses
from collections.abc import Callable, Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.pinterest_ads.settings import (
    ANALYTICS_COLUMNS,
    ANALYTICS_ENDPOINT_PATHS,
    ANALYTICS_ID_PARAM_NAMES,
    ANALYTICS_MAX_IDS,
    BASE_URL,
    ENTITY_ENDPOINT_PATHS,
    PAGE_SIZE,
    PINTEREST_ADS_CONFIG,
    EndpointType,
)
from posthog.temporal.data_imports.sources.pinterest_ads.utils import (
    _chunk_date_range,
    _chunk_list,
    _make_request,
    _normalize_row,
    build_session,
    fetch_account_currency,
    fetch_entity_ids,
    get_date_range,
)

ENTITY_RESUME_KIND = "entity"
ANALYTICS_RESUME_KIND = "analytics"


@dataclasses.dataclass
class PinterestAdsResumeConfig:
    """Resumable state for Pinterest Ads.

    Entity endpoints use a bookmark cursor. Analytics endpoints fan out across
    (id_batch, date_chunk) pairs and save only the cursor, so the payload
    written to Redis after every chunk stays small; the parent-entity list and
    date window are re-derived on resume. The ``kind`` discriminator lets us
    ignore state written by an incompatible endpoint type.
    """

    kind: str
    bookmark: str | None = None
    batch_index: int = 0
    date_chunk_index: int = 0


def pinterest_ads_source(
    ad_account_id: str,
    endpoint: str,
    access_token: str,
    resumable_source_manager: ResumableSourceManager[PinterestAdsResumeConfig],
    source_logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    if endpoint not in PINTEREST_ADS_CONFIG:
        raise ValueError(f"Unknown Pinterest Ads endpoint: {endpoint}")

    endpoint_config = PINTEREST_ADS_CONFIG[endpoint]

    def entity_items() -> Iterator[list[dict[str, Any]]]:
        session = build_session(access_token)
        yield from _iter_entity_rows(session, ad_account_id, endpoint, resumable_source_manager, source_logger)

    def analytics_items() -> Iterator[list[dict[str, Any]]]:
        session = build_session(access_token)
        yield from _iter_analytics_rows(
            session,
            ad_account_id,
            endpoint,
            resumable_source_manager,
            source_logger,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )

    items_fn: Callable[[], Iterator[list[dict[str, Any]]]]
    if endpoint_config.endpoint_type == EndpointType.ENTITY:
        items_fn = entity_items
    elif endpoint_config.endpoint_type == EndpointType.ANALYTICS:
        items_fn = analytics_items
    else:
        raise ValueError(f"Unknown endpoint type: {endpoint_config.endpoint_type}")

    return SourceResponse(
        name=endpoint,
        items=items_fn,
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=endpoint_config.partition_size,
        partition_mode=endpoint_config.partition_mode,
        partition_format=endpoint_config.partition_format,
        partition_keys=endpoint_config.partition_keys,
    )


def _load_resume_config(
    resumable_source_manager: ResumableSourceManager[PinterestAdsResumeConfig],
    expected_kind: str,
) -> PinterestAdsResumeConfig | None:
    if not resumable_source_manager.can_resume():
        return None
    state = resumable_source_manager.load_state()
    if state is None or state.kind != expected_kind:
        return None
    return state


def _iter_entity_rows(
    session: requests.Session,
    ad_account_id: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[PinterestAdsResumeConfig],
    source_logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    path = ENTITY_ENDPOINT_PATHS[endpoint].format(ad_account_id=ad_account_id)
    url = f"{BASE_URL}{path}"

    resume_config = _load_resume_config(resumable_source_manager, ENTITY_RESUME_KIND)
    bookmark: str | None = resume_config.bookmark if resume_config is not None else None
    if bookmark:
        source_logger.debug("pinterest_ads_resuming_entity", endpoint=endpoint)

    while True:
        params: dict[str, Any] = {"page_size": PAGE_SIZE}
        if bookmark:
            params["bookmark"] = bookmark

        data = _make_request(session, url, params)
        items = data.get("items", [])
        next_bookmark = data.get("bookmark")

        if items:
            yield items

        if not next_bookmark:
            break

        resumable_source_manager.save_state(PinterestAdsResumeConfig(kind=ENTITY_RESUME_KIND, bookmark=next_bookmark))
        bookmark = next_bookmark


def _iter_analytics_rows(
    session: requests.Session,
    ad_account_id: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[PinterestAdsResumeConfig],
    source_logger: FilteringBoundLogger,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> Iterator[list[dict[str, Any]]]:
    resume_config = _load_resume_config(resumable_source_manager, ANALYTICS_RESUME_KIND)
    start_batch_idx = resume_config.batch_index if resume_config is not None else 0
    start_chunk_idx = resume_config.date_chunk_index if resume_config is not None else 0

    # Re-derive setup on every run. Persisting the entity list on every cursor
    # save would balloon the Redis payload for large ad accounts; the cost of
    # one extra fetch on resume is negligible and primary-key dedupe handles
    # any minor drift in the entity list between original run and resume.
    entity_ids = fetch_entity_ids(session, ad_account_id, endpoint)
    if not entity_ids:
        source_logger.info("pinterest_ads_no_entities_found", endpoint=endpoint, ad_account_id=ad_account_id)
        return

    start_date, end_date = get_date_range(should_use_incremental_field, db_incremental_field_last_value)
    currency = fetch_account_currency(session, ad_account_id)

    if resume_config is not None:
        source_logger.info(
            "pinterest_ads_resuming_analytics",
            endpoint=endpoint,
            batch=start_batch_idx,
            chunk=start_chunk_idx,
        )
    else:
        source_logger.info(
            "pinterest_ads_fetching_analytics",
            endpoint=endpoint,
            entity_count=len(entity_ids),
            start_date=start_date,
            end_date=end_date,
            currency=currency,
        )

    path = ANALYTICS_ENDPOINT_PATHS[endpoint].format(ad_account_id=ad_account_id)
    url = f"{BASE_URL}{path}"
    id_param_name = ANALYTICS_ID_PARAM_NAMES[endpoint]

    date_chunks = _chunk_date_range(start_date, end_date)
    id_batches = _chunk_list(entity_ids, ANALYTICS_MAX_IDS)

    for batch_idx in range(start_batch_idx, len(id_batches)):
        batch = id_batches[batch_idx]
        chunk_start_idx = start_chunk_idx if batch_idx == start_batch_idx else 0

        for chunk_idx in range(chunk_start_idx, len(date_chunks)):
            chunk_start, chunk_end = date_chunks[chunk_idx]
            params: dict[str, Any] = {
                id_param_name: ",".join(batch),
                "start_date": chunk_start,
                "end_date": chunk_end,
                "columns": ",".join(ANALYTICS_COLUMNS),
                "granularity": "DAY",
            }

            data = _make_request(session, url, params)

            is_successful = isinstance(data, list)
            if is_successful:
                rows: list[dict[str, Any]] = []
                for row in data:
                    normalized = _normalize_row(row)
                    if currency:
                        normalized["currency"] = currency
                    rows.append(normalized)
                if rows:
                    yield rows
            else:
                source_logger.error(
                    "pinterest_ads_unexpected_analytics_response",
                    endpoint=endpoint,
                    response_type=type(data).__name__,
                )

            # Only advance the cursor on a successful response — a failed chunk must be retried on resume.
            if not is_successful:
                continue

            next_batch_idx, next_chunk_idx = _advance_analytics_cursor(
                batch_idx, chunk_idx, len(id_batches), len(date_chunks)
            )
            if next_batch_idx is not None and next_chunk_idx is not None:
                resumable_source_manager.save_state(
                    PinterestAdsResumeConfig(
                        kind=ANALYTICS_RESUME_KIND,
                        batch_index=next_batch_idx,
                        date_chunk_index=next_chunk_idx,
                    )
                )


def _advance_analytics_cursor(
    batch_idx: int, chunk_idx: int, num_batches: int, num_chunks: int
) -> tuple[int | None, int | None]:
    """Return the next (batch_idx, chunk_idx) pair, or (None, None) if done."""
    next_chunk_idx = chunk_idx + 1
    next_batch_idx = batch_idx
    if next_chunk_idx >= num_chunks:
        next_chunk_idx = 0
        next_batch_idx = batch_idx + 1
    if next_batch_idx >= num_batches:
        return None, None
    return next_batch_idx, next_chunk_idx
