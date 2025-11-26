import csv
import uuid
import typing
import zipfile
import datetime as dt
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import structlog
from bingads.v13.reporting import ReportingDownloadParameters
from dateutil.relativedelta import relativedelta

from .schemas import BingAdsResource

logger = structlog.get_logger(__name__)

ENVIRONMENT = "production"
REPORT_POLL_INTERVAL_MS = 5000
REPORT_TIMEOUT_MS = 360000


def parse_csv_to_dicts(csv_data: str) -> list[dict[str, Any]]:
    """Parse Bing Ads CSV report data into list of dictionaries."""
    if not csv_data or not csv_data.strip():
        return []

    # Remove BOM if present
    if csv_data.startswith("\ufeff"):
        csv_data = csv_data[1:]

    reader = csv.DictReader(csv_data.strip().split("\n"))

    # Convert "--" and empty strings to None
    return [{key: None if value in ("--", "") else value for key, value in row.items()} for row in reader]


def fetch_data_in_yearly_chunks(
    client: Any,
    resource: BingAdsResource,
    account_id: int,
    start_date: dt.date,
    end_date: dt.date,
) -> Iterator[list[dict]]:
    """Fetch data in yearly chunks to handle Bing Ads API limitations.

    Bing Ads API performs better with smaller date ranges. This function splits
    large date ranges into yearly chunks and aggregates errors for better visibility.
    """
    current_start = start_date
    errors: list[dict[str, typing.Any]] = []

    while current_start < end_date:
        chunk_end = min(
            current_start + relativedelta(years=1),
            end_date,
        )

        try:
            data_pages = client.get_data_by_resource(
                resource=resource,
                account_id=account_id,
                start_date=dt.datetime.combine(current_start, dt.time.min),
                end_date=dt.datetime.combine(chunk_end, dt.time.max),
            )

            for page in data_pages:
                if page:
                    yield page
        except Exception as e:
            errors.append(
                {
                    "start_date": current_start.isoformat(),
                    "end_date": chunk_end.isoformat(),
                    "error": str(e),
                    "error_type": type(e).__name__,
                }
            )

        # Move to the day after chunk_end to avoid duplicate dates at chunk boundaries
        current_start = chunk_end + dt.timedelta(days=1)

    if errors:
        logger.error(
            "Some data chunks failed to fetch",
            failed_chunks=len(errors),
            total_errors=errors,
        )


def build_report_request(
    service_factory: Any,
    report_config: dict,
    field_names: list[str],
    account_id: int,
    start_date: dt.datetime,
    end_date: dt.datetime,
) -> Any:
    """Build a Bing Ads report request object with all required configuration.

    The Bing Ads SDK uses a factory pattern to create report requests. This function
    encapsulates all the verbose setup into a single reusable function.
    """
    report_request = service_factory.create(report_config["report_type"])
    report_request.Aggregation = "Daily"
    report_request.ExcludeColumnHeaders = False
    report_request.ExcludeReportFooter = True
    report_request.ExcludeReportHeader = True
    report_request.Format = "Csv"
    report_request.ReturnOnlyCompleteData = False
    report_request.ReportName = report_config["report_name"]

    # Configure columns
    report_columns = service_factory.create(report_config["column_array_type"])
    setattr(report_columns, report_config["column_field"], field_names)
    report_request.Columns = report_columns

    # Configure scope
    scope = service_factory.create(report_config["scope_type"])
    scope.AccountIds = {"long": [account_id]}
    scope.Campaigns = None
    if report_config["scope_type"] == "AccountThroughAdGroupReportScope":
        scope.AdGroups = None
    report_request.Scope = scope

    # Configure date range
    report_time = service_factory.create("ReportTime")
    custom_date_range_start = service_factory.create("Date")
    custom_date_range_start.Day = start_date.day
    custom_date_range_start.Month = start_date.month
    custom_date_range_start.Year = start_date.year
    report_time.CustomDateRangeStart = custom_date_range_start

    custom_date_range_end = service_factory.create("Date")
    custom_date_range_end.Day = end_date.day
    custom_date_range_end.Month = end_date.month
    custom_date_range_end.Year = end_date.year
    report_time.CustomDateRangeEnd = custom_date_range_end

    report_request.Time = report_time

    return report_request


def download_and_extract_report_csv(
    reporting_service_manager: Any,
    report_request: Any,
    report_type: str,
    account_id: int,
) -> str:
    """Download report ZIP file and extract CSV content.

    Bing Ads Reporting API returns reports as ZIP files containing a single CSV.
    This function handles the download, extraction, and cleanup.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        filename = f"{report_type}_{account_id}_{uuid.uuid4()}.zip"

        download_params = ReportingDownloadParameters(
            report_request=report_request,
            result_file_directory=tmpdir,
            result_file_name=filename,
            overwrite_result_file=True,
            timeout_in_milliseconds=REPORT_TIMEOUT_MS,
        )

        result_file_path = reporting_service_manager.download_file(download_params)

        result_path = Path(result_file_path)
        with zipfile.ZipFile(result_path, "r") as zip_file:
            csv_files = [name for name in zip_file.namelist() if name.endswith(".csv")]
            if not csv_files:
                raise ValueError("No CSV file found in report ZIP")
            csv_data = zip_file.read(csv_files[0]).decode("utf-8")

    return csv_data
