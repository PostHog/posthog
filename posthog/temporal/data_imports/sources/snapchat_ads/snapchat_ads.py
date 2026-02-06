from typing import Any, Optional, cast

from dlt.sources.helpers.rest_client.auth import BearerTokenAuth

from posthog.temporal.common.utils import make_sync_retryable_with_exponential_backoff
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.snapchat_ads.settings import BASE_URL, SNAPCHAT_ADS_CONFIG, EndpointType
from posthog.temporal.data_imports.sources.snapchat_ads.utils import (
    SnapchatAdsAPIError,
    SnapchatAdsPaginator,
    SnapchatErrorHandler,
    SnapchatStatsResource,
)


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
        resource["write_disposition"] = {  # type: ignore[typeddict-item]
            "disposition": "merge",
            "strategy": "upsert",
        }
    else:
        resource["write_disposition"] = "replace"

    return resource


def snapchat_ads_source(
    ad_account_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    access_token: str,
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    """Snapchat Ads source using rest_api_resources with date chunking support."""

    endpoint_config = SNAPCHAT_ADS_CONFIG[endpoint]
    endpoint_type = endpoint_config.endpoint_type

    if endpoint_type is None:
        raise ValueError(f"Endpoint type is not set for {endpoint}")

    base_resource = get_snapchat_resource(endpoint, ad_account_id, should_use_incremental_field)

    if endpoint_type == EndpointType.STATS:
        resources = SnapchatStatsResource.setup_stats_resources(
            base_resource, ad_account_id, should_use_incremental_field, db_incremental_field_last_value
        )
    else:
        resources = [base_resource]

    # Create REST API config
    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": BearerTokenAuth(token=access_token),
        },
        "resource_defaults": {
            "primary_key": "id" if endpoint_type == EndpointType.ENTITY else None,
            "write_disposition": "replace",
        },
        "resources": cast(list, resources),
    }

    # Add paginator to each resource to avoid shared state issues
    resources_list = config["resources"]
    if isinstance(resources_list, list):
        for resource_item in resources_list:
            if isinstance(resource_item, dict):
                if "endpoint" not in resource_item:
                    resource_item["endpoint"] = {}
                resource_endpoint = resource_item.get("endpoint")
                if isinstance(resource_endpoint, dict):
                    resource_endpoint["paginator"] = SnapchatAdsPaginator()

    # Apply retry logic to the entire resource creation process
    dlt_resources = make_sync_retryable_with_exponential_backoff(
        lambda: rest_api_resources(config, team_id, job_id, db_incremental_field_last_value),
        max_attempts=5,
        initial_retry_delay=60,  # Snapchat has 600 req/min limit, so 60s should be enough
        max_retry_delay=3600,  # Cap at 1 hour
        exponential_backoff_coefficient=2,
        retryable_exceptions=(SnapchatAdsAPIError, Exception),
        is_exception_retryable=SnapchatErrorHandler.is_retryable,
    )()

    if endpoint_type == EndpointType.STATS:
        items = SnapchatStatsResource.process_resources(dlt_resources)
    else:
        assert len(dlt_resources) == 1, f"Expected 1 resource for {endpoint_type} endpoint, got {len(dlt_resources)}"
        items = dlt_resources[0]

    items = SnapchatStatsResource.apply_stream_transformations(endpoint_type, items)

    return SourceResponse(
        name=endpoint,
        items=lambda: items,
        primary_keys=list(endpoint_config.resource["primary_key"])
        if isinstance(endpoint_config.resource["primary_key"], list | tuple)
        else None,
        partition_count=1,
        partition_size=endpoint_config.partition_size,
        partition_mode=endpoint_config.partition_mode,
        partition_format=endpoint_config.partition_format,
        partition_keys=endpoint_config.partition_keys,
    )
