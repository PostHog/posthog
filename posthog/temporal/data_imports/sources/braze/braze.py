from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urljoin

import requests

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse


class BrazeAPIError(Exception):
    pass


def parse_iso_date(date_str: str) -> datetime:
    """Parse ISO format date string to datetime"""
    return datetime.fromisoformat(date_str.replace("Z", "+00:00"))


def format_date(dt: datetime) -> str:
    """Format datetime to ISO string for Braze API"""
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def get_endpoint_config(endpoint: str) -> dict[str, Any]:
    """Get configuration for each endpoint type"""
    configs = {
        "campaigns": {
            "path": "/campaigns/list",
            "params": {"page": 0, "page_size": 100},
            "data_selector": "campaigns",
            "primary_key": "id",
        },
        "campaigns_analytics": {
            "path": "/campaigns/data_series",
            "params": {"length": 100},  # days
            "data_selector": "data",
            "primary_key": None,
            "requires_ids": True,
            "parent_endpoint": "campaigns",
        },
        "canvases": {
            "path": "/canvas/list",
            "params": {"page": 0, "page_size": 100},
            "data_selector": "canvases",
            "primary_key": "id",
        },
        "canvases_analytics": {
            "path": "/canvas/data_series",
            "params": {"length": 14},  # days
            "data_selector": "data",
            "primary_key": None,
            "requires_ids": True,
            "parent_endpoint": "canvases",
        },
        "events": {
            "path": "/events/list",
            "params": {"page": 0, "page_size": 100},
            "data_selector": "events",
            "primary_key": None,
        },
        "events_analytics": {
            "path": "/events/data_series",
            "params": {"length": 100},  # days
            "data_selector": "data",
            "primary_key": None,
            "requires_ids": True,
            "parent_endpoint": "events",
            "id_field": "event",
        },
        "kpi_daily_new_users": {
            "path": "/kpi/new_users/data_series",
            "params": {"length": 100},  # days
            "data_selector": "data",
            "primary_key": None,
        },
        "kpi_daily_active_users": {
            "path": "/kpi/dau/data_series",
            "params": {"length": 100},  # days
            "data_selector": "data",
            "primary_key": None,
        },
        "kpi_daily_app_uninstalls": {
            "path": "/kpi/uninstalls/data_series",
            "params": {"length": 100},  # days
            "data_selector": "data",
            "primary_key": None,
        },
        "cards": {
            "path": "/feed/list",
            "params": {"page": 0, "page_size": 100},
            "data_selector": "cards",
            "primary_key": "id",
        },
        "cards_analytics": {
            "path": "/feed/data_series",
            "params": {"length": 100},  # days
            "data_selector": "data",
            "primary_key": None,
            "requires_ids": True,
            "parent_endpoint": "cards",
            "id_field": "card_id",
        },
        "segments": {
            "path": "/segments/list",
            "params": {"page": 0, "page_size": 100},
            "data_selector": "segments",
            "primary_key": "id",
        },
        "segments_analytics": {
            "path": "/segments/data_series",
            "params": {"length": 100},  # days
            "data_selector": "data",
            "primary_key": None,
            "requires_ids": True,
            "parent_endpoint": "segments",
            "id_field": "segment_id",
        },
    }
    return configs[endpoint]


def fetch_paginated_data(
    base_url: str,
    api_key: str,
    endpoint: str,
    config: dict[str, Any],
    start_date: datetime | None = None,
) -> list[dict[str, Any]]:
    """Fetch paginated data from Braze API"""
    headers = {"Authorization": f"Bearer {api_key}"}
    all_data = []
    page = 0

    while True:
        params = config["params"].copy()
        params["page"] = page

        if start_date and "end_time" in config["params"]:
            params["end_time"] = format_date(datetime.now())
            params["start_time"] = format_date(start_date)

        url = urljoin(base_url, config["path"])
        response = requests.get(url, headers=headers, params=params)

        if response.status_code != 200:
            raise BrazeAPIError(f"API request failed: {response.status_code} - {response.text}")

        data = response.json()

        if "message" in data and data["message"] != "success":
            raise BrazeAPIError(f"API error: {data.get('message')}")

        items = data.get(config["data_selector"], [])
        if not items:
            break

        all_data.extend(items)

        # Check if there are more pages
        if len(items) < params.get("page_size", 100):
            break

        page += 1

    return all_data


def fetch_time_series_data(
    base_url: str,
    api_key: str,
    endpoint: str,
    config: dict[str, Any],
    start_date: datetime | None = None,
    db_incremental_field_last_value: Any | None = None,
    ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Fetch time series data from Braze API with date windowing"""
    headers = {"Authorization": f"Bearer {api_key}"}
    all_data = []

    # Determine the start date
    if db_incremental_field_last_value:
        if isinstance(db_incremental_field_last_value, str):
            current_start = parse_iso_date(db_incremental_field_last_value)
        else:
            current_start = db_incremental_field_last_value
    elif start_date:
        current_start = start_date
    else:
        # Default to 100 days ago
        current_start = datetime.now() - timedelta(days=100)

    end_date = datetime.now()

    # Fetch data in windows based on the length parameter
    window_days = config["params"]["length"]

    while current_start < end_date:
        window_end = min(current_start + timedelta(days=window_days), end_date)

        params = {
            "end_time": format_date(window_end),
            "start_time": format_date(current_start),
        }

        # Add IDs if required
        if ids and config.get("requires_ids"):
            base_endpoint = endpoint.removesuffix("_analytics")
            id_field = config.get("id_field", f"{base_endpoint}_id")
            # Braze API may accept comma-separated IDs or require multiple calls
            # For simplicity, we'll make separate calls for each ID
            for item_id in ids:
                item_params = params.copy()
                item_params[id_field] = item_id

                url = urljoin(base_url, config["path"])
                response = requests.get(url, headers=headers, params=item_params)

                if response.status_code != 200:
                    # Some IDs might not have data, continue
                    continue

                data = response.json()

                if "message" in data and data["message"] != "success":
                    continue

                items = data.get(config["data_selector"], [])
                # Add the ID to each item for context
                for item in items:
                    item[id_field] = item_id
                all_data.extend(items)
        else:
            # No IDs required, just fetch the data
            url = urljoin(base_url, config["path"])
            response = requests.get(url, headers=headers, params=params)

            if response.status_code != 200:
                raise BrazeAPIError(f"API request failed: {response.status_code} - {response.text}")

            data = response.json()

            if "message" in data and data["message"] != "success":
                raise BrazeAPIError(f"API error: {data.get('message')}")

            items = data.get(config["data_selector"], [])
            all_data.extend(items)

        current_start = window_end

    return all_data


def braze_source(
    api_key: str,
    base_url: str,
    endpoint: str,
    start_date: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any | None = None,
) -> SourceResponse:
    """Main source function for fetching data from Braze"""
    config = get_endpoint_config(endpoint)

    # Parse start date
    start_dt = parse_iso_date(start_date) if start_date else None

    # Check if this endpoint requires parent data (IDs)
    if config.get("requires_ids"):
        parent_endpoint = config["parent_endpoint"]
        parent_config = get_endpoint_config(parent_endpoint)

        # Fetch parent data to get IDs
        parent_data = fetch_paginated_data(base_url, api_key, parent_endpoint, parent_config)

        # Extract IDs
        id_field = config.get("id_field")
        if id_field:
            # For events, the ID field is the name
            ids = [item.get("name") for item in parent_data if item.get("name")]
        else:
            ids = [item.get("id") for item in parent_data if item.get("id")]

        # Fetch analytics data for each ID
        data = fetch_time_series_data(
            base_url,
            api_key,
            endpoint,
            config,
            start_dt,
            db_incremental_field_last_value if should_use_incremental_field else None,
            ids,
        )
    else:
        # Check if this is a time series endpoint
        if endpoint in [
            "campaigns_analytics",
            "canvases_analytics",
            "events_analytics",
            "kpi_daily_new_users",
            "kpi_daily_active_users",
            "kpi_daily_app_uninstalls",
            "cards_analytics",
            "segments_analytics",
        ]:
            data = fetch_time_series_data(
                base_url,
                api_key,
                endpoint,
                config,
                start_dt,
                db_incremental_field_last_value if should_use_incremental_field else None,
            )
        else:
            # Regular paginated endpoint
            data = fetch_paginated_data(base_url, api_key, endpoint, config, start_dt)

    def item_generator():
        yield data

    primary_keys = [config["primary_key"]] if config.get("primary_key") else None

    return SourceResponse(
        items=item_generator(),
        primary_keys=primary_keys,
        partition_keys=["time"] if endpoint in INCREMENTAL_ENDPOINTS else None,
        partition_mode="datetime" if endpoint in INCREMENTAL_ENDPOINTS else None,
    )


# List of incremental endpoints (same as in settings.py)
INCREMENTAL_ENDPOINTS = [
    "campaigns_analytics",
    "canvases_analytics",
    "events_analytics",
    "kpi_daily_new_users",
    "kpi_daily_active_users",
    "kpi_daily_app_uninstalls",
    "cards_analytics",
    "segments_analytics",
]


def validate_credentials(api_key: str, base_url: str) -> bool:
    """Validate Braze API credentials by making a test request"""
    headers = {"Authorization": f"Bearer {api_key}"}
    url = urljoin(base_url, "/campaigns/list")

    try:
        response = requests.get(url, headers=headers, params={"page": 0, "page_size": 1})
        return response.status_code == 200
    except Exception:
        return False
