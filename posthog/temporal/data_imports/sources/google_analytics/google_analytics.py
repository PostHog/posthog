from datetime import datetime, timezone
from typing import Any, Iterator

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    RunReportRequest,
    RunReportResponse,
)
from google.oauth2.credentials import Credentials

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.generated_configs import GoogleAnalyticsSourceConfig
from posthog.temporal.data_imports.sources.google_analytics.settings import ENDPOINTS
from posthog.warehouse.models import Integration
from products.data_warehouse.backend.types import IncrementalFieldType

# Report configurations
# Maps report names to their respective dimensions and metrics
REPORT_CONFIGS = {
    "daily_active_users": {
        "dimensions": ["date"],
        "metrics": ["activeUsers"],
    },
    "weekly_active_users": {
        "dimensions": ["date", "week"],
        "metrics": ["active7DayUsers"],
    },
    "devices": {
        "dimensions": ["date", "deviceCategory", "operatingSystem", "browser"],
        "metrics": ["activeUsers", "sessions", "screenPageViews"],
    },
    "locations": {
        "dimensions": ["date", "country", "city"],
        "metrics": ["activeUsers", "sessions"],
    },
    "pages": {
        "dimensions": ["date", "pageTitle", "pagePath"],
        "metrics": ["screenPageViews", "activeUsers", "averageSessionDuration"],
    },
    "traffic_sources": {
        "dimensions": ["date", "sessionSource", "sessionMedium", "sessionCampaignName"],
        "metrics": ["sessions", "activeUsers", "newUsers"],
    },
    "sessions": {
        "dimensions": ["date", "sessionSource", "sessionMedium"],
        "metrics": ["sessions", "averageSessionDuration", "bounceRate"],
    },
    "events": {
        "dimensions": ["date", "eventName"],
        "metrics": ["eventCount", "eventCountPerUser"],
    },
    "conversions": {
        "dimensions": ["date", "eventName"],
        "metrics": ["conversions"],
    },
    "user_acquisition": {
        "dimensions": ["date", "firstUserSource", "firstUserMedium", "firstUserCampaignName"],
        "metrics": ["newUsers", "sessions"],
    },
    "traffic_acquisition": {
        "dimensions": ["date", "sessionSource", "sessionMedium"],
        "metrics": ["sessions", "engagedSessions", "newUsers"],
    },
    "engagement": {
        "dimensions": ["date"],
        "metrics": ["engagedSessions", "averageSessionDuration", "engagementRate"],
    },
}


def _get_credentials_from_integration(config: GoogleAnalyticsSourceConfig, team_id: int) -> Credentials:
    """Get OAuth credentials from the integration."""
    integration = Integration.objects.get(
        id=config.google_analytics_integration_id,
        team_id=team_id,
    )

    access_token = integration.sensitive_config.get("access_token")
    refresh_token = integration.sensitive_config.get("refresh_token")

    if not access_token or not refresh_token:
        raise ValueError("Missing OAuth credentials in integration")

    return Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=integration.config.get("client_id"),
        client_secret=integration.sensitive_config.get("client_secret"),
    )


def validate_credentials(config: GoogleAnalyticsSourceConfig, team_id: int) -> bool:
    """Validate Google Analytics credentials by attempting a simple API call."""
    try:
        credentials = _get_credentials_from_integration(config, team_id)
        client = BetaAnalyticsDataClient(credentials=credentials)

        # Make a simple request to validate credentials
        request = RunReportRequest(
            property=f"properties/{config.property_id}",
            dimensions=[Dimension(name="date")],
            metrics=[Metric(name="activeUsers")],
            date_ranges=[
                DateRange(
                    start_date="7daysAgo",
                    end_date="today",
                )
            ],
            limit=1,
        )

        client.run_report(request)
        return True
    except Exception:
        return False


def get_schemas(config: GoogleAnalyticsSourceConfig, team_id: int) -> list[str]:
    """Get available schemas (reports) for Google Analytics."""
    # Validate credentials first
    if not validate_credentials(config, team_id):
        return []

    return ENDPOINTS


def _parse_report_response(response: RunReportResponse) -> Iterator[dict[str, Any]]:
    """Parse a Google Analytics report response into a list of dictionaries."""
    if not response.rows:
        return

    # Get dimension and metric names
    dimension_names = [header.name for header in response.dimension_headers]
    metric_names = [header.name for header in response.metric_headers]

    # Convert each row to a dictionary
    for row in response.rows:
        record: dict[str, Any] = {}

        # Add dimensions
        for i, dimension_value in enumerate(row.dimension_values):
            record[dimension_names[i]] = dimension_value.value

        # Add metrics
        for i, metric_value in enumerate(row.metric_values):
            metric_name = metric_names[i]
            value = metric_value.value

            # Try to convert to numeric if possible
            try:
                if "." in value:
                    record[metric_name] = float(value)
                else:
                    record[metric_name] = int(value)
            except (ValueError, AttributeError):
                record[metric_name] = value

        yield record


def _fetch_report_data(
    client: BetaAnalyticsDataClient,
    property_id: str,
    report_config: dict[str, Any],
    start_date: str,
    end_date: str,
    offset: int = 0,
    limit: int = 10000,
) -> RunReportResponse:
    """Fetch data from Google Analytics for a specific report."""
    request = RunReportRequest(
        property=f"properties/{property_id}",
        dimensions=[Dimension(name=dim) for dim in report_config["dimensions"]],
        metrics=[Metric(name=metric) for metric in report_config["metrics"]],
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        limit=limit,
        offset=offset,
    )

    return client.run_report(request)


def google_analytics_source(
    config: GoogleAnalyticsSourceConfig,
    schema_name: str,
    team_id: int,
    should_use_incremental_field: bool,
    incremental_field: str | None,
    incremental_field_type: IncrementalFieldType | None,
    db_incremental_field_last_value: str | None,
) -> SourceResponse:
    """
    Main source function for Google Analytics data.

    This function pulls data from Google Analytics Data API (GA4) and yields it
    as dictionaries for the data pipeline to process.
    """
    # Get OAuth credentials
    credentials = _get_credentials_from_integration(config, team_id)
    client = BetaAnalyticsDataClient(credentials=credentials)

    # Get report configuration
    if schema_name not in REPORT_CONFIGS:
        raise ValueError(f"Unknown report: {schema_name}")

    report_config = REPORT_CONFIGS[schema_name]

    # Determine date range
    if should_use_incremental_field and db_incremental_field_last_value:
        # Parse the last value and start from the next day
        if incremental_field_type == IncrementalFieldType.Date:
            last_date = datetime.fromisoformat(db_incremental_field_last_value.replace("Z", "+00:00"))
            # Start from the day after the last synced date
            start_date = last_date.strftime("%Y-%m-%d")
        else:
            start_date = "30daysAgo"
    else:
        # Default to last 30 days for initial sync
        start_date = "30daysAgo"

    end_date = "today"

    def data_generator() -> Iterator[dict[str, Any]]:
        """Generator that yields report data with pagination."""
        offset = 0
        limit = 10000  # GA4 max limit per request

        while True:
            response = _fetch_report_data(
                client=client,
                property_id=config.property_id,
                report_config=report_config,
                start_date=start_date,
                end_date=end_date,
                offset=offset,
                limit=limit,
            )

            # Yield all rows from this page
            row_count = 0
            for record in _parse_report_response(response):
                yield record
                row_count += 1

            # If we got fewer rows than the limit, we're done
            if row_count < limit:
                break

            # Move to next page
            offset += limit

    return SourceResponse(
        items=data_generator(),
        primary_keys=["date"] if "date" in report_config["dimensions"] else report_config["dimensions"][:1],
        partition_keys=["date"] if "date" in report_config["dimensions"] else None,
        partition_mode="datetime" if "date" in report_config["dimensions"] else None,
        partition_format="%Y%m%d" if "date" in report_config["dimensions"] else None,
    )
