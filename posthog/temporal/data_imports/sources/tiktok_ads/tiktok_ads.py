import copy
import dataclasses
from collections.abc import Callable, Iterable, Iterator
from typing import Any, Optional, cast

from posthog.temporal.common.utils import make_sync_retryable_with_exponential_backoff
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resource
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.tiktok_ads.settings import BASE_URL, TIKTOK_ADS_CONFIG, EndpointType
from posthog.temporal.data_imports.sources.tiktok_ads.utils import (
    TikTokAdsAPIError,
    TikTokAdsAuth,
    TikTokAdsPaginator,
    TikTokErrorHandler,
    TikTokReportResource,
)


@dataclasses.dataclass
class TikTokAdsResumeConfig:
    """Resume state for TikTok Ads endpoints.

    Entity/account endpoints run as a single page-number-paginated resource;
    ``chunk_index`` is always 0 and ``chunk_start_date``/``chunk_end_date``
    are ``None``.

    Report endpoints split the date range into sequential chunks. Between
    runs the chunk boundaries can shift (``datetime.now()`` advances, or the
    incremental cursor moves), so matching by ``chunk_index`` alone risks
    resuming into a different date window. The saved chunk's
    ``(start_date, end_date)`` pair is the stable identity we match on; we
    only fall back to ``chunk_index`` when dates are absent (non-report
    endpoints).

    Duplicates on resume are deduped by the endpoint's primary key.
    """

    page: int
    chunk_index: int = 0
    chunk_start_date: Optional[str] = None
    chunk_end_date: Optional[str] = None


def get_tiktok_resource(
    endpoint_name: str,
    advertiser_id: str,
    should_use_incremental_field: bool = False,
) -> dict[str, Any]:
    """Build the base REST resource config for a TikTok Ads endpoint.

    The result is fed to ``rest_api_resource`` (singular) per date chunk —
    see ``tiktok_ads_source``. Report endpoints layer date-chunked copies
    on top of this base via ``TikTokReportResource.setup_report_resources``.
    """
    if endpoint_name not in TIKTOK_ADS_CONFIG:
        raise ValueError(f"Unknown endpoint: {endpoint_name}")

    config = TIKTOK_ADS_CONFIG[endpoint_name]
    resource = dict(config.resource)

    endpoint_data = resource.get("endpoint")
    if not isinstance(endpoint_data, dict):
        raise ValueError(f"Invalid endpoint configuration for {endpoint_name}")
    endpoint = endpoint_data.copy()
    params_data = endpoint.get("params")
    if params_data is None:
        params = {}
    else:
        params = params_data.copy()

    params = {
        key: value.format(advertiser_id=advertiser_id, start_date="{start_date}", end_date="{end_date}")
        if isinstance(value, str)
        else value
        for key, value in params.items()
    }

    endpoint["params"] = params
    resource["endpoint"] = endpoint

    if should_use_incremental_field and config.incremental_fields:
        resource["write_disposition"] = {
            "disposition": "merge",
            "strategy": "upsert",
        }
    else:
        resource["write_disposition"] = "replace"

    return resource


def _build_chunk_resources(
    endpoint: str,
    advertiser_id: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    endpoint_type: EndpointType,
) -> list[dict[str, Any]]:
    base_resource = get_tiktok_resource(endpoint, advertiser_id, should_use_incremental_field)

    if endpoint_type == EndpointType.REPORT:
        return TikTokReportResource.setup_report_resources(
            base_resource, advertiser_id, should_use_incremental_field, db_incremental_field_last_value
        )
    return [base_resource]


def _iter_chunk(
    chunk_resource: dict[str, Any],
    access_token: str,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any],
    initial_paginator_state: Optional[dict[str, Any]],
    resume_hook: Callable[[Optional[dict[str, Any]]], None],
) -> Iterable[Any]:
    # Each chunk gets its own paginator instance to avoid shared state when
    # several chunks run back-to-back.
    chunk_copy = copy.deepcopy(chunk_resource)
    endpoint_cfg = chunk_copy.get("endpoint")
    if not isinstance(endpoint_cfg, dict):
        endpoint_cfg = {}
        chunk_copy["endpoint"] = endpoint_cfg
    endpoint_cfg["paginator"] = TikTokAdsPaginator()

    chunk_config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": TikTokAdsAuth(access_token),
        },
        "resource_defaults": {
            "write_disposition": "replace",
        },
        "resources": cast(list, [chunk_copy]),
    }

    # NOTE: ``rest_api_resource`` returns a lazy iterable; actual HTTP
    # requests happen when the caller consumes it in ``process_resources``.
    # The retry below therefore only guards the (fast, rare-to-fail)
    # resource-construction step — mid-pagination TikTok errors propagate
    # out and are not retried here. Per-request retries would need to live
    # inside the paginator or rest_client. Kept as-is to preserve existing
    # behaviour.
    resource = make_sync_retryable_with_exponential_backoff(
        lambda: rest_api_resource(
            chunk_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=resume_hook,
            initial_paginator_state=initial_paginator_state,
        ),
        max_attempts=5,
        initial_retry_delay=300,  # TikTok's 5-minute circuit breaker
        max_retry_delay=3600 * 5,
        exponential_backoff_coefficient=2,
        retryable_exceptions=(TikTokAdsAPIError, Exception),
        is_exception_retryable=TikTokErrorHandler.is_retryable,
    )()

    return resource


def _get_chunk_dates(chunk_resource: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """Extract the chunk's ``(start_date, end_date)`` params, or ``(None, None)``."""
    endpoint_cfg = chunk_resource.get("endpoint")
    if not isinstance(endpoint_cfg, dict):
        return None, None
    params = endpoint_cfg.get("params")
    if not isinstance(params, dict):
        return None, None
    start = params.get("start_date")
    end = params.get("end_date")
    return (start if isinstance(start, str) else None, end if isinstance(end, str) else None)


def _resolve_resume_chunk_index(loaded: TikTokAdsResumeConfig, chunk_resources: list[dict[str, Any]]) -> Optional[int]:
    """Find the current chunk matching the saved checkpoint, or ``None`` if stale.

    For non-report endpoints the saved dates are ``None`` and we validate
    the raw ``chunk_index`` against the current chunk count. For report
    endpoints the chunk list can shift between runs (``datetime.now()``
    advances), so we match on the chunk's ``(start_date, end_date)`` pair
    — a stable identity — and discard the state if no chunk matches.
    """
    if loaded.chunk_start_date is None and loaded.chunk_end_date is None:
        if 0 <= loaded.chunk_index < len(chunk_resources):
            return loaded.chunk_index
        return None

    for idx, chunk in enumerate(chunk_resources):
        start, end = _get_chunk_dates(chunk)
        if start == loaded.chunk_start_date and end == loaded.chunk_end_date:
            return idx
    return None


def tiktok_ads_source(
    advertiser_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    access_token: str,
    db_incremental_field_last_value: Optional[Any],
    resumable_source_manager: ResumableSourceManager[TikTokAdsResumeConfig],
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    """TikTok Ads source using rest_api_resource with per-chunk resume support."""

    endpoint_config = TIKTOK_ADS_CONFIG[endpoint]
    endpoint_type = endpoint_config.endpoint_type

    if endpoint_type is None:
        raise ValueError(f"Endpoint type is not set for {endpoint}")

    chunk_resources = _build_chunk_resources(
        endpoint, advertiser_id, should_use_incremental_field, db_incremental_field_last_value, endpoint_type
    )

    resumed_chunk_index: Optional[int] = None
    resumed_page: Optional[int] = None
    if resumable_source_manager.can_resume():
        loaded = resumable_source_manager.load_state()
        if loaded is not None:
            matching_idx = _resolve_resume_chunk_index(loaded, chunk_resources)
            if matching_idx is not None:
                resumed_chunk_index = matching_idx
                resumed_page = loaded.page

    def items_iterator() -> Iterator[Any]:
        for chunk_index, chunk_resource in enumerate(chunk_resources):
            if resumed_chunk_index is not None and chunk_index < resumed_chunk_index:
                continue

            initial_paginator_state: Optional[dict[str, Any]] = None
            if resumed_chunk_index is not None and chunk_index == resumed_chunk_index:
                initial_paginator_state = {"page": resumed_page}

            chunk_start, chunk_end = _get_chunk_dates(chunk_resource)

            def make_save_checkpoint(
                idx: int, start: Optional[str], end: Optional[str]
            ) -> Callable[[Optional[dict[str, Any]]], None]:
                def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
                    # The paginator only emits state while there are pages
                    # left, so ``state["page"]`` points at the page still to
                    # fetch. Redis TTL handles cleanup on completion.
                    if state and state.get("page") is not None:
                        resumable_source_manager.save_state(
                            TikTokAdsResumeConfig(
                                page=int(state["page"]),
                                chunk_index=idx,
                                chunk_start_date=start,
                                chunk_end_date=end,
                            )
                        )

                return save_checkpoint

            resource = _iter_chunk(
                chunk_resource,
                access_token,
                team_id,
                job_id,
                db_incremental_field_last_value,
                initial_paginator_state,
                make_save_checkpoint(chunk_index, chunk_start, chunk_end),
            )

            flat = TikTokReportResource.process_resources([resource])
            yield from TikTokReportResource.apply_stream_transformations(endpoint_type, flat)

    return SourceResponse(
        name=endpoint,
        items=items_iterator,
        primary_keys=list(endpoint_config.resource["primary_key"])
        if isinstance(endpoint_config.resource["primary_key"], list | tuple)
        else None,
        partition_count=1,
        partition_size=endpoint_config.partition_size,
        partition_mode=endpoint_config.partition_mode,
        partition_format=endpoint_config.partition_format,
        partition_keys=endpoint_config.partition_keys,
    )
