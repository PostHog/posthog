from datetime import datetime, timedelta
from typing import Any, Optional, cast

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.tiktok_ads.settings import (
    BASE_URL,
    MAX_TIKTOK_DAYS_FOR_REPORT_ENDPOINTS,
    TIKTOK_ADS_CONFIG,
)
from posthog.temporal.data_imports.sources.tiktok_ads.utils import (
    TikTokAdsAuth,
    TikTokAdsPaginator,
    create_date_chunked_resources,
    flatten_tiktok_report_record,
    flatten_tiktok_reports,
    get_incremental_date_range,
    is_report_endpoint,
)


def get_tiktok_resource(
    endpoint_name: str,
    advertiser_id: str,
    should_use_incremental_field: bool = False,
    start_date: str | None = None,
    end_date: str | None = None,
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
        key: value.format(advertiser_id=advertiser_id, start_date=start_date or "", end_date=end_date or "")
        if isinstance(value, str)
        else value
        for key, value in params.items()
    }

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
    is_report = is_report_endpoint(endpoint)

    if is_report:
        # For report endpoints, we need date chunking
        starts_at, ends_at = get_incremental_date_range(should_use_incremental_field, db_incremental_field_last_value)

        # If not using incremental field, use full date range
        if not should_use_incremental_field:
            ends_at = datetime.now().strftime("%Y-%m-%d")
            starts_at = (datetime.now() - timedelta(days=MAX_TIKTOK_DAYS_FOR_REPORT_ENDPOINTS)).strftime("%Y-%m-%d")

        # Get base resource configuration (dates will be set per chunk)
        base_resource = get_tiktok_resource(endpoint, advertiser_id, should_use_incremental_field)

        resources = create_date_chunked_resources(base_resource, starts_at, ends_at, advertiser_id)
    else:
        # For non-report endpoints, use single resource without dates
        base_resource = get_tiktok_resource(endpoint, advertiser_id, should_use_incremental_field)
        resources = [base_resource]

    # Create REST API config
    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": TikTokAdsAuth(access_token),
        },
        "resource_defaults": {
            "primary_key": "id" if not is_report else None,
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

    dlt_resources = rest_api_resources(config, team_id, job_id, db_incremental_field_last_value)

    if is_report and len(dlt_resources) > 1:

        def combined_resource():
            for resource in dlt_resources:
                for item in resource:
                    if isinstance(item, list):
                        yield from flatten_tiktok_reports(item)
                    else:
                        yield flatten_tiktok_report_record(item)

        items = combined_resource()
    else:
        assert len(dlt_resources) == 1, "Expected 1 resource, got {}".format(len(dlt_resources))
        resource = dlt_resources[0]

        if is_report:

            def flattened_resource():
                for item in resource:
                    if isinstance(item, list):
                        yield from flatten_tiktok_reports(item)
                    elif isinstance(item, dict):
                        yield flatten_tiktok_report_record(item)
                    else:
                        # Handle other types by converting to dict if possible
                        yield item

            items = flattened_resource()
        else:
            items = resource

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
