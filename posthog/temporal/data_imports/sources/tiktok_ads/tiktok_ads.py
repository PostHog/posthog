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

    Entity/account endpoints run as a single page-number-paginated resource
    (``chunk_index`` is always 0). Report endpoints split the date range into
    sequential chunks; resume must capture both which chunk was in flight and
    the page within it. Duplicates on resume are deduped by the endpoint's
    primary key.
    """

    page: int
    chunk_index: int = 0


def get_tiktok_resource(
    endpoint_name: str,
    advertiser_id: str,
    should_use_incremental_field: bool = False,
) -> dict[str, Any]:
    """Get TikTok resource configuration for rest_api_resources."""
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

    resume_config: TikTokAdsResumeConfig | None = None
    if resumable_source_manager.can_resume():
        loaded = resumable_source_manager.load_state()
        # Only honour a saved checkpoint whose chunk still exists in this run's
        # chunk list; otherwise the resume state is stale (e.g. the date range
        # shifted) and we fall back to a fresh run.
        if loaded is not None and 0 <= loaded.chunk_index < len(chunk_resources):
            resume_config = loaded

    def items_iterator() -> Iterator[Any]:
        for chunk_index, chunk_resource in enumerate(chunk_resources):
            if resume_config is not None and chunk_index < resume_config.chunk_index:
                continue

            initial_paginator_state: Optional[dict[str, Any]] = None
            if resume_config is not None and chunk_index == resume_config.chunk_index:
                initial_paginator_state = {"page": resume_config.page}

            def make_save_checkpoint(idx: int) -> Callable[[Optional[dict[str, Any]]], None]:
                def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
                    # The paginator only emits state while there are pages
                    # left, so ``state["page"]`` points at the page still to
                    # fetch. Redis TTL handles cleanup on completion.
                    if state and state.get("page") is not None:
                        resumable_source_manager.save_state(
                            TikTokAdsResumeConfig(page=int(state["page"]), chunk_index=idx)
                        )

                return save_checkpoint

            resource = _iter_chunk(
                chunk_resource,
                access_token,
                team_id,
                job_id,
                db_incremental_field_last_value,
                initial_paginator_state,
                make_save_checkpoint(chunk_index),
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
