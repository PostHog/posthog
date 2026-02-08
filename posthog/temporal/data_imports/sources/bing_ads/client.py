from collections.abc import Generator
from datetime import datetime
from typing import Any

import structlog
from bingads import AuthorizationData, OAuthTokens, OAuthWebAuthCodeGrant, ServiceClient
from bingads.v13 import reporting

from posthog.settings import integrations

from .schemas import REPORT_CONFIG, RESOURCE_SCHEMAS, BingAdsResource
from .utils import (
    ENVIRONMENT,
    REPORT_POLL_INTERVAL_MS,
    build_report_request,
    download_and_extract_report_csv,
    parse_csv_to_dicts,
)

logger = structlog.get_logger(__name__)


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
                languages = getattr(campaign, "Languages", None)
                languages_list = list(languages.string) if languages and hasattr(languages, "string") else None
                result.append(
                    {
                        "Id": campaign.Id,
                        "Name": campaign.Name,
                        "Status": campaign.Status,
                        "CampaignType": getattr(campaign, "CampaignType", None),
                        "BudgetType": getattr(campaign, "BudgetType", None),
                        "DailyBudget": getattr(campaign, "DailyBudget", None),
                        "AudienceAdsBidAdjustment": getattr(campaign, "AudienceAdsBidAdjustment", None),
                        "Languages": languages_list,
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

        # Build report request using SDK's factory pattern
        report_request = build_report_request(
            service_factory=reporting_service_manager._service_client.factory,
            report_config=report_config,
            field_names=schema["field_names"],
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
        )

        # Download and extract CSV from ZIP
        csv_data = download_and_extract_report_csv(
            reporting_service_manager=reporting_service_manager,
            report_request=report_request,
            report_type=report_config["report_type"],
            account_id=account_id,
        )

        return parse_csv_to_dicts(csv_data)

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
