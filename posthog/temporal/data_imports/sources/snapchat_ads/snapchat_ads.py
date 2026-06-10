import dataclasses
from collections.abc import Callable, Iterator
from typing import Any, Optional, cast

from posthog.temporal.common.utils import make_sync_retryable_with_exponential_backoff
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resource
from posthog.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.snapchat_ads.settings import BASE_URL, SNAPCHAT_ADS_CONFIG, EndpointType
from posthog.temporal.data_imports.sources.snapchat_ads.utils import (
    SnapchatAdsAPIError,
    SnapchatAdsPaginator,
    SnapchatErrorHandler,
    SnapchatStatsResource,
    fetch_account_currency,
)


@dataclasses.dataclass
class SnapchatResumeConfig:
    # Which chunk the next request targets. Non-stats endpoints produce a
    # single chunk and always use index 0. Stats endpoints fan out across
    # date-chunked resources, so the index identifies which chunk to resume.
    chunk_index: int
    # next_link URL for cursor-based pagination within ``chunk_index``.
    # ``None`` means resume at the start of ``chunk_index``.
    next_link: Optional[str] = None


def get_snapchat_resource(
    endpoint_name: str,
    ad_account_id: str,
    should_use_incremental_field: bool = False,
):
    """Get Snapchat resource configuration for rest_api_resources."""
    if endpoint_name not in SNAPCHAT_ADS_CONFIG:
        raise ValueError(f"Unknown endpoint: {endpoint_name}")

    config = SNAPCHAT_ADS_CONFIG[endpoint_name]
    resource = config.resource.copy()

    # Update endpoint params with template variables
    endpoint_data = resource.get("endpoint")
    if not isinstance(endpoint_data, dict):
        raise ValueError(f"Invalid endpoint configuration for {endpoint_name}")
    endpoint = endpoint_data.copy()
    params_data = endpoint.get("params")
    if params_data is None:
        params = {}
    else:
        params = params_data.copy()

    # Replace template variables in params
    params = {
        key: (
            value.format(ad_account_id=ad_account_id, start_time="{start_time}", end_time="{end_time}")
            if isinstance(value, str)
            else value
        )
        for key, value in params.items()
    }

    # Replace path template
    path = endpoint.get("path", "")
    if isinstance(path, str):
        endpoint["path"] = path.format(ad_account_id=ad_account_id)

    endpoint["params"] = params
    resource["endpoint"] = endpoint

    # Set write disposition based on incremental field usage
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
    ad_account_id: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> tuple[list[dict], EndpointType]:
    endpoint_config = SNAPCHAT_ADS_CONFIG[endpoint]
    endpoint_type = endpoint_config.endpoint_type

    if endpoint_type is None:
        raise ValueError(f"Endpoint type is not set for {endpoint}")

    base_resource = get_snapchat_resource(endpoint, ad_account_id, should_use_incremental_field)

    if endpoint_type == EndpointType.STATS:
        chunk_resources = SnapchatStatsResource.setup_stats_resources(
            base_resource, ad_account_id, should_use_incremental_field, db_incremental_field_last_value
        )
    else:
        chunk_resources = [base_resource]

    # Each chunk gets its own paginator instance — paginator state is per-chunk
    # and sharing a single instance across chunks would leak cursors between them.
    for chunk_resource in chunk_resources:
        endpoint_cfg = chunk_resource.get("endpoint")
        if isinstance(endpoint_cfg, dict):
            endpoint_cfg["paginator"] = SnapchatAdsPaginator()

    return chunk_resources, endpoint_type


def _iter_chunk_rows(
    chunk_resource: dict,
    access_token: str,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any],
    resume_hook: Callable[[Optional[dict[str, Any]]], None],
    initial_paginator_state: Optional[dict[str, Any]],
) -> Iterator[Any]:
    """Build and iterate the underlying rest_api_resource for a single chunk."""

    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": BearerTokenAuth(token=access_token),
        },
        "resource_defaults": {
            "write_disposition": "replace",
        },
        "resources": cast(list, [chunk_resource]),
    }

    # Apply retry logic to resource creation (mirrors the pre-resumable behavior).
    # Snapchat has a 600 req/min limit, so 60s initial backoff is a safe floor.
    resource = make_sync_retryable_with_exponential_backoff(
        lambda: rest_api_resource(
            config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=resume_hook,
            initial_paginator_state=initial_paginator_state,
        ),
        max_attempts=5,
        initial_retry_delay=60,
        max_retry_delay=3600,
        exponential_backoff_coefficient=2,
        retryable_exceptions=(SnapchatAdsAPIError, Exception),
        is_exception_retryable=SnapchatErrorHandler.is_retryable,
    )()

    yield from resource


def _iter_rows(
    ad_account_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    access_token: str,
    resumable_source_manager: ResumableSourceManager[SnapchatResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool,
) -> Iterator[list[dict[str, Any]]]:
    chunk_resources, endpoint_type = _build_chunk_resources(
        endpoint, ad_account_id, should_use_incremental_field, db_incremental_field_last_value
    )

    resume_config: Optional[SnapchatResumeConfig] = (
        resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    )
    start_chunk = resume_config.chunk_index if resume_config else 0

    # Guard against stale state whose chunk_index no longer fits the current
    # chunk layout (date range shifts produce a different chunk count).
    if start_chunk >= len(chunk_resources):
        start_chunk = 0
        resume_config = None

    account_currency: Optional[str] = None
    if endpoint_type == EndpointType.STATS:
        account_currency = fetch_account_currency(ad_account_id, access_token)
    else:
        assert len(chunk_resources) == 1, (
            f"Expected 1 resource for {endpoint_type} endpoint, got {len(chunk_resources)}"
        )

    for chunk_index, chunk_resource in enumerate(chunk_resources):
        if chunk_index < start_chunk:
            continue

        initial_paginator_state: Optional[dict[str, Any]] = None
        if resume_config and chunk_index == start_chunk and resume_config.next_link:
            initial_paginator_state = {"next_link": resume_config.next_link}

        def save_checkpoint(state: Optional[dict[str, Any]], _chunk_index: int = chunk_index) -> None:
            # Match mailchimp/reddit_ads: only persist when there's a concrete
            # cursor to resume to. Chunk advancement is handled explicitly
            # after the iterator exhausts, and Redis TTL handles cleanup on
            # completion.
            next_link = state.get("next_link") if state else None
            if not next_link:
                return
            resumable_source_manager.save_state(SnapchatResumeConfig(chunk_index=_chunk_index, next_link=next_link))

        for page in _iter_chunk_rows(
            chunk_resource=chunk_resource,
            access_token=access_token,
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=db_incremental_field_last_value,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        ):
            if isinstance(page, list):
                rows = page
            elif isinstance(page, dict):
                rows = [page]
            elif page is None:
                rows = []
            else:
                rows = list(page)

            transformed = SnapchatStatsResource.apply_stream_transformations(
                endpoint_type, rows, currency=account_currency
            )
            if transformed:
                yield transformed

        # Move the checkpoint forward to the start of the next chunk so a
        # restart doesn't redo chunks we've already finished. The final chunk
        # has no successor, so skip the write there and let the Redis TTL
        # clean up the last checkpoint.
        if chunk_index + 1 < len(chunk_resources):
            resumable_source_manager.save_state(SnapchatResumeConfig(chunk_index=chunk_index + 1, next_link=None))


def snapchat_ads_source(
    ad_account_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    access_token: str,
    db_incremental_field_last_value: Optional[Any],
    resumable_source_manager: ResumableSourceManager[SnapchatResumeConfig],
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    """Snapchat Ads source using rest_api_resource with date chunking and resume support."""

    endpoint_config = SNAPCHAT_ADS_CONFIG[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: _iter_rows(
            ad_account_id=ad_account_id,
            endpoint=endpoint,
            team_id=team_id,
            job_id=job_id,
            access_token=access_token,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
        ),
        primary_keys=list(endpoint_config.resource["primary_key"])
        if isinstance(endpoint_config.resource["primary_key"], list | tuple)
        else None,
        partition_count=1,
        partition_size=endpoint_config.partition_size,
        partition_mode=endpoint_config.partition_mode,
        partition_format=endpoint_config.partition_format,
        partition_keys=endpoint_config.partition_keys,
    )
