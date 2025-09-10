from datetime import datetime
from typing import Any, Optional

import requests
import structlog
from dateutil import parser
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator

from posthog.temporal.data_imports.pipelines.helpers import initial_datetime
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import _get_column_hints, _get_primary_keys
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource

logger = structlog.get_logger(__name__)


def _get_metrics_date_range(
    should_use_incremental_field: bool, db_incremental_field_last_value: Optional[Any] = None
) -> tuple[str, str]:
    ends_at = datetime.now().strftime("%Y-%m-%dT00:00:00Z")

    if should_use_incremental_field and db_incremental_field_last_value:
        try:
            if isinstance(db_incremental_field_last_value, datetime.datetime):
                last_datetime = db_incremental_field_last_value
            elif isinstance(db_incremental_field_last_value, datetime.date):
                last_datetime = datetime.combine(db_incremental_field_last_value, datetime.min.time())
            elif isinstance(db_incremental_field_last_value, str):
                date = parser.parse(db_incremental_field_last_value)
                last_datetime = date.strftime("%Y-%m-%dT00:00:00Z")
            else:
                last_datetime = datetime.fromisoformat(str(db_incremental_field_last_value))

            starts_at = last_datetime.strftime("%Y-%m-%dT00:00:00Z")

        except Exception:
            starts_at = initial_datetime.strftime("%Y-%m-%dT00:00:00Z")
    else:
        starts_at = initial_datetime.strftime("%Y-%m-%dT00:00:00Z")

    return starts_at, ends_at


def get_resource(
    name: str,
    account_id: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any] = None,
) -> EndpointResource:
    # Calculate dates dynamically for metrics endpoints only
    starts_at, ends_at = None, None
    if name.endswith("_metrics"):
        starts_at, ends_at = _get_metrics_date_range(should_use_incremental_field, db_incremental_field_last_value)

    resources: dict[str, EndpointResource] = {
        "campaigns": {
            "name": "campaigns",
            "table_name": "campaigns",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "data",
                "path": f"/ad_accounts/{account_id}/campaigns",
                "params": {
                    "page.size": 100,
                    "modified_at[after]": {
                        "type": "incremental",
                        "cursor_path": "modified_at",
                        "initial_value": initial_datetime.strftime("%Y-%m-%dT00:00:00Z"),
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
        "ad_groups": {
            "name": "ad_groups",
            "table_name": "ad_groups",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "data",
                "path": f"/ad_accounts/{account_id}/ad_groups",
                "params": {
                    "page.size": 100,
                    "modified_at[after]": {
                        "type": "incremental",
                        "cursor_path": "modified_at",
                        "initial_value": initial_datetime.strftime("%Y-%m-%dT00:00:00Z"),
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
        "ads": {
            "name": "ads",
            "table_name": "ads",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "data",
                "path": f"/ad_accounts/{account_id}/ads",
                "params": {
                    "page.size": 100,
                    "modified_at[after]": {
                        "type": "incremental",
                        "cursor_path": "modified_at",
                        "initial_value": initial_datetime.strftime("%Y-%m-%dT00:00:00Z"),
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
        "campaign_metrics": {
            "name": "campaign_metrics",
            "table_name": "campaign_metrics",
            "primary_key": ["campaign_id", "date"],
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "data.metrics",
                "path": f"/ad_accounts/{account_id}/reports",
                "method": "POST",
                "params": {"page.size": 100},
                "json": {
                    "data": {
                        "breakdowns": ["CAMPAIGN_ID", "DATE"],
                        "fields": ["CAMPAIGN_ID", "DATE", "IMPRESSIONS", "CLICKS", "SPEND"],
                        "starts_at": starts_at,
                        "ends_at": ends_at,
                        "time_zone_id": "UTC",
                    }
                },
            },
            "table_format": "delta",
        },
        "ad_group_metrics": {
            "name": "ad_group_metrics",
            "table_name": "ad_group_metrics",
            "primary_key": ["ad_group_id", "date"],
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "data.metrics",
                "path": f"/ad_accounts/{account_id}/reports",
                "method": "POST",
                "params": {"page.size": 100},
                "json": {
                    "data": {
                        "breakdowns": ["AD_GROUP_ID", "DATE"],
                        "fields": ["AD_GROUP_ID", "DATE", "IMPRESSIONS", "CLICKS", "SPEND"],
                        "starts_at": starts_at,
                        "ends_at": ends_at,
                        "time_zone_id": "UTC",
                    }
                },
            },
            "table_format": "delta",
        },
        "ad_metrics": {
            "name": "ad_metrics",
            "table_name": "ad_metrics",
            "primary_key": ["ad_id", "date"],
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "data.metrics",
                "path": f"/ad_accounts/{account_id}/reports",
                "method": "POST",
                "params": {"page.size": 100},
                "json": {
                    "data": {
                        "breakdowns": ["AD_ID", "DATE"],
                        "fields": ["AD_ID", "DATE", "IMPRESSIONS", "CLICKS", "SPEND"],
                        "starts_at": starts_at,
                        "ends_at": ends_at,
                        "time_zone_id": "UTC",
                    }
                },
            },
            "table_format": "delta",
        },
    }

    return resources[name]


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

    return SourceResponse(
        name=endpoint,
        items=resource,
        primary_keys=_get_primary_keys(resource),
        column_hints=_get_column_hints(resource),
        partition_count=None,
    )
