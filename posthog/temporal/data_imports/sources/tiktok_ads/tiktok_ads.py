from typing import Any, Optional, cast

from posthog.temporal.common.utils import make_sync_retryable_with_exponential_backoff
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.tiktok_ads.settings import BASE_URL, TIKTOK_ADS_CONFIG, EndpointType
from posthog.temporal.data_imports.sources.tiktok_ads.utils import (
    TikTokAdsAPIError,
    TikTokAdsAuth,
    TikTokAdsPaginator,
    TikTokErrorHandler,
    TikTokReportResource,
)


def get_tiktok_resource(
    endpoint_name: str,
    advertiser_id: str,
    should_use_incremental_field: bool = False,
):
    """Get TikTok resource configuration for rest_api_resources."""
    if endpoint_name not in TIKTOK_ADS_CONFIG:
        raise ValueError(f"Unknown endpoint: {endpoint_name}")

    config = TIKTOK_ADS_CONFIG[endpoint_name]
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
        key: value.format(advertiser_id=advertiser_id, start_date="{start_date}", end_date="{end_date}")
        if isinstance(value, str)
        else value
        for key, value in params.items()
    }

    endpoint["params"] = params
    resource["endpoint"] = endpoint

    # Set write disposition based on incremental field usage
    if should_use_incremental_field and config.incremental_fields:
        resource["write_disposition"] = {  # type: ignore[typeddict-item]
            "disposition": "merge",
            "strategy": "upsert",
        }
    else:
        resource["write_disposition"] = "replace"

    return resource


def tiktok_ads_source(
    advertiser_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    access_token: str,
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    """TikTok Ads source using rest_api_resources with date chunking support."""

    endpoint_config = TIKTOK_ADS_CONFIG[endpoint]
    endpoint_type = endpoint_config.endpoint_type

    if endpoint_type is None:
        raise ValueError(f"Endpoint type is not set for {endpoint}")

    base_resource = get_tiktok_resource(endpoint, advertiser_id, should_use_incremental_field)

    if endpoint_type == EndpointType.REPORT:
        resources = TikTokReportResource.setup_report_resources(
            base_resource, advertiser_id, should_use_incremental_field, db_incremental_field_last_value
        )
    else:
        resources = [base_resource]

    # Create REST API config
    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": TikTokAdsAuth(access_token),
        },
        "resource_defaults": {
            "primary_key": "id" if endpoint_type == EndpointType.ENTITY else None,
            "write_disposition": "replace",
        },
        "resources": cast(list, resources),
    }

    # Add paginator to each resource individually to avoid shared state
    resources_list = config["resources"]
    if isinstance(resources_list, list):
        for resource_item in resources_list:
            if isinstance(resource_item, dict):
                if "endpoint" not in resource_item:
                    resource_item["endpoint"] = {}
                resource_endpoint = resource_item.get("endpoint")
                if isinstance(resource_endpoint, dict):
                    resource_endpoint["paginator"] = TikTokAdsPaginator()

    # Apply retry logic to the entire resource creation process
    dlt_resources = make_sync_retryable_with_exponential_backoff(
        lambda: rest_api_resources(config, team_id, job_id, db_incremental_field_last_value),
        max_attempts=5,
        initial_retry_delay=300,  # TikTok's 5-minute circuit breaker
        max_retry_delay=3600 * 5,  # Cap at 5 hours
        exponential_backoff_coefficient=2,  # Standard exponential backoff: attempt^2
        retryable_exceptions=(TikTokAdsAPIError, Exception),
        is_exception_retryable=TikTokErrorHandler.is_retryable,
    )()

    if endpoint_type == EndpointType.REPORT:
        items = TikTokReportResource.process_resources(dlt_resources)
    else:
        assert len(dlt_resources) == 1, f"Expected 1 resource for {endpoint_type} endpoint, got {len(dlt_resources)}"
        items = dlt_resources[0]

    # Apply appropriate transformations based on endpoint type
    items = TikTokReportResource.apply_stream_transformations(endpoint_type, items)

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=list(endpoint_config.resource["primary_key"])
        if isinstance(endpoint_config.resource["primary_key"], list | tuple)
        else None,
        partition_count=1,
        partition_size=endpoint_config.partition_size,
        partition_mode=endpoint_config.partition_mode,
        partition_format=endpoint_config.partition_format,
        partition_keys=endpoint_config.partition_keys,
    )
