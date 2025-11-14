import csv
import uuid
import zipfile
import tempfile
from collections.abc import Generator
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from bingads import AuthorizationData, OAuthTokens, OAuthWebAuthCodeGrant, ServiceClient
from bingads.v13 import reporting

from posthog.settings import integrations

from .schemas import REPORT_CONFIG, RESOURCE_SCHEMAS, BingAdsResource

logger = structlog.get_logger(__name__)

ENVIRONMENT = "production"
REPORT_POLL_INTERVAL_MS = 5000
REPORT_TIMEOUT_MS = 360000


class BingAdsClient:
    def __init__(self, access_token: str, refresh_token: str, developer_token: str):
        self.developer_token = developer_token
        self._customer_id: int | None = None

        # The SDK requires OAuth setup
        self.oauth = OAuthWebAuthCodeGrant(
            client_id=integrations.BING_ADS_CLIENT_ID,
            client_secret=integrations.BING_ADS_CLIENT_SECRET,
            redirection_uri="",
        )

        # Access private member to set token - this is the SDK's expected pattern
        self.oauth._oauth_tokens = OAuthTokens(
            access_token=access_token,
            access_token_expires_in_seconds=3600,
            refresh_token=refresh_token,
        )

        self.authorization_data = AuthorizationData(
            account_id=None,
            customer_id=None,
            developer_token=developer_token,
            authentication=self.oauth,
        )

    def get_customer_id(self) -> int | None:
        if self._customer_id is not None:
            return self._customer_id

        try:
            service_client = ServiceClient(
                service="CustomerManagementService",
                version=13,
                authorization_data=self.authorization_data,
                environment=ENVIRONMENT,
            )

            user = service_client.GetUser(UserId=None).User
            self._customer_id = user.CustomerId
            return self._customer_id
        except Exception as e:
            logger.warning("Failed to fetch customer ID", error=str(e), error_type=type(e).__name__)
            return None

    def get_campaigns(self, account_id: int, customer_id: int) -> Generator[list[dict[str, Any]], None, None]:
        self.authorization_data.account_id = account_id
        self.authorization_data.customer_id = customer_id

        service_client = ServiceClient(
            service="CampaignManagementService",
            version=13,
            authorization_data=self.authorization_data,
            environment=ENVIRONMENT,
        )

        campaigns = service_client.GetCampaignsByAccountId(AccountId=account_id)

        result = []
        if campaigns and campaigns.Campaign:
            for campaign in campaigns.Campaign:
                result.append(
                    {
                        "Id": campaign.Id,
                        "Name": campaign.Name,
                        "Status": campaign.Status,
                        "BudgetType": getattr(campaign, "BudgetType", None),
                        "DailyBudget": getattr(campaign, "DailyBudget", None),
                        "CampaignType": getattr(campaign, "CampaignType", None),
                        "TimeZone": getattr(campaign, "TimeZone", None),
                    }
                )

        yield result

    def get_performance_report(
        self,
        resource: BingAdsResource,
        account_id: int,
        customer_id: int,
        start_date: datetime,
        end_date: datetime,
    ) -> list[dict[str, Any]]:
        report_config = REPORT_CONFIG[resource]
        schema = RESOURCE_SCHEMAS[resource]

        self.authorization_data.account_id = account_id
        self.authorization_data.customer_id = customer_id

        reporting_service_manager = reporting.ReportingServiceManager(
            authorization_data=self.authorization_data,
            poll_interval_in_milliseconds=REPORT_POLL_INTERVAL_MS,
            environment=ENVIRONMENT,
        )

        reporting_service = reporting_service_manager._service_client

        report_request = reporting_service.factory.create(report_config["report_type"])
        report_request.Aggregation = "Daily"
        report_request.ExcludeColumnHeaders = False
        report_request.ExcludeReportFooter = False
        report_request.ExcludeReportHeader = False
        report_request.Format = "Csv"
        report_request.ReturnOnlyCompleteData = False
        report_request.ReportName = report_config["report_name"]

        report_columns = reporting_service.factory.create(report_config["column_array_type"])
        setattr(report_columns, report_config["column_field"], schema["field_names"])
        report_request.Columns = report_columns

        scope = reporting_service.factory.create(report_config["scope_type"])
        scope.AccountIds = {"long": [account_id]}
        scope.Campaigns = None
        if report_config["scope_type"] == "AccountThroughAdGroupReportScope":
            scope.AdGroups = None
        report_request.Scope = scope

        report_time = reporting_service.factory.create("ReportTime")
        custom_date_range_start = reporting_service.factory.create("Date")
        custom_date_range_start.Day = start_date.day
        custom_date_range_start.Month = start_date.month
        custom_date_range_start.Year = start_date.year
        report_time.CustomDateRangeStart = custom_date_range_start

        custom_date_range_end = reporting_service.factory.create("Date")
        custom_date_range_end.Day = end_date.day
        custom_date_range_end.Month = end_date.month
        custom_date_range_end.Year = end_date.year
        report_time.CustomDateRangeEnd = custom_date_range_end

        report_request.Time = report_time

        with tempfile.TemporaryDirectory() as tmpdir:
            filename = f"{report_config['report_type']}_{account_id}_{uuid.uuid4()}.zip"
            reporting_download_parameters = reporting.ReportingDownloadParameters(
                report_request=report_request,
                result_file_directory=tmpdir,
                result_file_name=filename,
                overwrite_result_file=True,
                timeout_in_milliseconds=REPORT_TIMEOUT_MS,
            )

            result_file_path = reporting_service_manager.download_file(reporting_download_parameters)

            result_path = Path(result_file_path)
            with zipfile.ZipFile(result_path, "r") as zip_file:
                csv_files = [name for name in zip_file.namelist() if name.endswith(".csv")]
                if not csv_files:
                    raise ValueError("No CSV file found in report ZIP")
                csv_data = zip_file.read(csv_files[0]).decode("utf-8")

        return self._parse_csv_to_dicts(csv_data)

    def get_data_by_resource(
        self,
        resource: BingAdsResource,
        account_id: int,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> Generator[list[dict[str, Any]], None, None]:
        customer_id = self.get_customer_id()
        if customer_id is None:
            raise ValueError("Failed to fetch customer ID")

        if resource == BingAdsResource.CAMPAIGNS:
            yield from self.get_campaigns(account_id, customer_id)
        elif resource in REPORT_CONFIG:
            if not start_date or not end_date:
                raise ValueError("start_date and end_date required for performance reports")
            yield self.get_performance_report(resource, account_id, customer_id, start_date, end_date)
        else:
            raise ValueError(f"Unsupported resource: {resource}")

    @staticmethod
    def _parse_csv_to_dicts(csv_data: str) -> list[dict[str, Any]]:
        if not csv_data or not csv_data.strip():
            return []

        if csv_data.startswith("\ufeff"):
            csv_data = csv_data[1:]

        lines = csv_data.strip().split("\n")

        header_line_index = None
        for i, line in enumerate(lines):
            if "TimePeriod" in line and ":" not in line:
                header_line_index = i
                break

        if header_line_index is None:
            for i, line in enumerate(lines):
                if any(col in line for col in ["CampaignName", "CampaignId", "Impressions"]) and ":" not in line:
                    header_line_index = i
                    break

        if header_line_index is None:
            logger.warning("Could not find header line in CSV data")
            return []

        data_lines = []
        for i in range(header_line_index, len(lines)):
            line = lines[i]
            if line.startswith("©") or line.startswith('"©'):
                break
            data_lines.append(line)

        if not data_lines:
            return []

        reader = csv.DictReader(data_lines)
        result = []

        for row in reader:
            cleaned_row = {key: None if value in ("--", "") else value for key, value in row.items()}
            result.append(cleaned_row)

        return result
