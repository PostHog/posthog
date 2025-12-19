from datetime import date, datetime, timedelta
from typing import Any, Optional

import structlog
from dateutil import parser
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator

from posthog.temporal.data_imports.pipelines.helpers import initial_datetime
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from posthog.temporal.data_imports.sources.reddit_ads.settings import REDDIT_ADS_CONFIG

logger = structlog.get_logger(__name__)


def _get_incremental_date_range(
    should_use_incremental_field: bool, db_incremental_field_last_value: Optional[Any] = None
) -> tuple[str, str]:
    # Reddit Ads API will throw bad request error if the start or end time params has minutes or seconds
    # so we set it to the floor of the current or next hour for the start and end times respectively
    ends_at = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:00:00Z")

    if should_use_incremental_field and db_incremental_field_last_value:
        try:
            if isinstance(db_incremental_field_last_value, datetime):
                last_datetime = db_incremental_field_last_value
            elif isinstance(db_incremental_field_last_value, date):
                last_datetime = datetime.combine(db_incremental_field_last_value, datetime.min.time())
            elif isinstance(db_incremental_field_last_value, str):
                last_datetime = parser.parse(db_incremental_field_last_value)
            else:
                last_datetime = datetime.fromisoformat(str(db_incremental_field_last_value))

            starts_at = last_datetime.strftime("%Y-%m-%dT%H:00:00Z")

        except Exception:
            starts_at = initial_datetime.strftime("%Y-%m-%dT%H:00:00Z")
    else:
        starts_at = initial_datetime.strftime("%Y-%m-%dT%H:00:00Z")

    return starts_at, ends_at


def get_resource(
    name: str,
    account_id: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any] = None,
) -> EndpointResource:
    if name not in REDDIT_ADS_CONFIG:
        raise ValueError(f"Unknown endpoint: {name}")

    config = REDDIT_ADS_CONFIG[name]

    # Build endpoint configuration
    endpoint = config.resource["endpoint"]
    if not isinstance(endpoint, dict):
        raise ValueError(f"Expected endpoint to be a dict, got {type(endpoint)}")

    # Calculate dates dynamically for incremental endpoints only
    starts_at, ends_at = None, None
    if should_use_incremental_field:
        starts_at, ends_at = _get_incremental_date_range(should_use_incremental_field, db_incremental_field_last_value)

    endpoint_config = {
        "data_selector": endpoint["data_selector"],
        "path": endpoint["path"].format(account_id=account_id) if endpoint["path"] else "",
        "method": endpoint["method"],
        "params": endpoint["params"].copy() if endpoint["params"] else {},
    }

    # Handle incremental parameters for non-metrics endpoints
    if should_use_incremental_field and endpoint.get("incremental"):
        incremental_config = endpoint["incremental"]
        if incremental_config and incremental_config.get("cursor_path") == "modified_at":
            if isinstance(endpoint_config["params"], dict):
                endpoint_config["params"]["modified_at[after]"] = {
                    "type": "incremental",
                    "cursor_path": "modified_at",
                    "initial_value": starts_at,
                }

    # Handle JSON body for POST requests (metrics endpoints)
    if endpoint.get("json"):
        json_data = endpoint["json"]
        if json_data is not None:
            json_body = json_data.copy()
            if endpoint.get("incremental"):
                json_body["data"]["starts_at"] = starts_at
                json_body["data"]["ends_at"] = ends_at
            endpoint_config["json"] = json_body

    # Build the complete resource configuration
    resource: EndpointResource = {
        "name": config.resource["name"],
        "table_name": config.resource["table_name"],
        "primary_key": config.resource["primary_key"],
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": endpoint_config,  # type: ignore[typeddict-item]
        "table_format": config.resource["table_format"],
    }

    return resource


class RedditAdsPaginator(BasePaginator):
    """Custom paginator for Reddit Ads API"""

    def __init__(self):
        super().__init__()
        self._next_url = None
        self._has_next_page = False

    def update_state(self, response: Response, data: Optional[Any] = None) -> None:
        """Update pagination state from response"""
        try:
            response_data = response.json()
            pagination = response_data.get("pagination", {})
            self._next_url = pagination.get("next_url")

            self._has_next_page = bool(self._next_url)

        except Exception as e:
            logger.exception("Failed to parse pagination response", error=str(e))
            self._next_url = None
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        """Update request with next page URL"""
        if self._next_url:
            request.url = self._next_url


def reddit_ads_source(
    account_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    access_token: str,
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
):
    config: RESTAPIConfig = {
        "client": {
            "base_url": "https://ads-api.reddit.com/api/v3",
            "auth": {
                "type": "bearer",
                "token": access_token,
            },
            "headers": {
                "Content-Type": "application/json",
            },
            "paginator": RedditAdsPaginator(),
        },
        "resource_defaults": {
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
        },
        "resources": [
            get_resource(endpoint, account_id, should_use_incremental_field, db_incremental_field_last_value)
        ],
    }

    resources = rest_api_resources(config, team_id, job_id, db_incremental_field_last_value)
    assert len(resources) == 1
    resource = resources[0]

    endpoint_config = REDDIT_ADS_CONFIG[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=list(endpoint_config.resource["primary_key"])
        if isinstance(endpoint_config.resource["primary_key"], list | tuple)
        else None,
        partition_count=1,
        partition_size=endpoint_config.partition_size,
        partition_mode=endpoint_config.partition_mode,
        partition_format=endpoint_config.partition_format,
        partition_keys=endpoint_config.partition_keys,
    )
