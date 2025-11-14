import csv
from collections.abc import Generator
from datetime import UTC, datetime
from io import StringIO
from typing import Any

import requests

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse


def validate_credentials(api_token: str, app_id: str) -> bool:
    """Validate AppsFlyer credentials by making a test API call."""
    # Use the installs_report endpoint with a minimal date range to test credentials
    base_url = "https://hq1.appsflyer.com/api/raw-data/export/app"
    url = f"{base_url}/{app_id}/installs_report/v5"

    # Test with a small date range (today only)
    from_date = datetime.now(UTC).strftime("%Y-%m-%d")
    to_date = from_date

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Accept": "text/csv",
    }

    params = {
        "from": from_date,
        "to": to_date,
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        # 200 means success, 401 means invalid credentials
        # 404 means app not found
        return response.status_code in [200, 204]  # 204 = no data but valid credentials
    except Exception:
        return False


def fetch_appsflyer_data(
    api_token: str,
    app_id: str,
    endpoint: str,
    from_date: str,
    to_date: str,
) -> list[dict[str, Any]]:
    """Fetch data from AppsFlyer API.

    Args:
        api_token: AppsFlyer API token (Bearer token)
        app_id: AppsFlyer app ID
        endpoint: Report endpoint name (e.g., 'installs_report')
        from_date: Start date in YYYY-MM-DD format
        to_date: End date in YYYY-MM-DD format

    Returns:
        List of dictionaries containing the report data
    """
    # Determine the API path based on endpoint type
    if endpoint in ["partners_report", "partners_by_date_report", "geo_by_date_report", "daily_report"]:
        # Aggregate data endpoint
        base_url = "https://hq1.appsflyer.com/api/agg-data/export/app"
    else:
        # Raw data endpoint
        base_url = "https://hq1.appsflyer.com/api/raw-data/export/app"

    url = f"{base_url}/{app_id}/{endpoint}/v5"

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Accept": "text/csv",
    }

    params = {
        "from": from_date,
        "to": to_date,
    }

    # For aggregate reports, add timezone parameter (default to UTC)
    if endpoint in ["partners_report", "partners_by_date_report", "geo_by_date_report", "daily_report"]:
        params["timezone"] = "UTC"

    response = requests.get(url, headers=headers, params=params, timeout=120)
    response.raise_for_status()

    # Parse CSV response
    csv_data = response.text
    if not csv_data or csv_data.strip() == "":
        return []

    # Parse CSV into list of dicts
    csv_reader = csv.DictReader(StringIO(csv_data))
    rows = []
    for row in csv_reader:
        # AppsFlyer returns empty string values, convert them to None
        cleaned_row = {k: (v if v != "" else None) for k, v in row.items()}
        rows.append(cleaned_row)

    return rows


def appsflyer_source(
    api_token: str,
    app_id: str,
    endpoint: str,
    start_date: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: str | None,
) -> SourceResponse:
    """Create a source response for AppsFlyer data.

    Args:
        api_token: AppsFlyer API token
        app_id: AppsFlyer app ID
        endpoint: Report endpoint name
        start_date: Start date for data sync in YYYY-MM-DD format
        should_use_incremental_field: Whether to use incremental syncing
        db_incremental_field_last_value: Last synced value for incremental field

    Returns:
        SourceResponse with data generator
    """
    # Determine date range for API call
    if should_use_incremental_field and db_incremental_field_last_value:
        # For incremental syncs, start from the last synced value
        # AppsFlyer timestamps are in format "2025-01-15 12:34:56"
        # We need to convert to YYYY-MM-DD for the API
        try:
            if " " in db_incremental_field_last_value:
                # It's a datetime string
                from_date = db_incremental_field_last_value.split(" ")[0]
            else:
                # It's already a date string
                from_date = db_incremental_field_last_value
        except Exception:
            from_date = start_date
    else:
        from_date = start_date

    # Use today as the end date
    to_date = datetime.now(UTC).strftime("%Y-%m-%d")

    def data_generator() -> Generator[list[dict[str, Any]], None, None]:
        """Generator that yields batches of data from AppsFlyer."""
        data = fetch_appsflyer_data(
            api_token=api_token,
            app_id=app_id,
            endpoint=endpoint,
            from_date=from_date,
            to_date=to_date,
        )

        if data:
            # Yield data in batches to avoid memory issues
            batch_size = 1000
            for i in range(0, len(data), batch_size):
                batch = data[i : i + batch_size]
                yield batch

    # Determine primary keys based on endpoint type
    if endpoint in ["partners_report", "partners_by_date_report"]:
        primary_keys = ["date", "media_source", "campaign"]
    elif endpoint in ["geo_by_date_report"]:
        primary_keys = ["date", "country_code"]
    elif endpoint == "daily_report":
        primary_keys = ["date"]
    else:
        # Raw data reports use appsflyer_id and event_time as composite key
        primary_keys = ["appsflyer_id", "event_time"]

    return SourceResponse(
        items=data_generator(),
        primary_keys=primary_keys,
    )
