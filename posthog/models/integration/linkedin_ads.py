"""LinkedIn Ads integration."""

import requests
import structlog
from rest_framework.exceptions import ValidationError

from posthog.egress.slack.client import SlackWebClient as WebClient

from . import common, model

logger = structlog.get_logger(__name__)


class LinkedInAdsIntegration:
    integration: model.Integration

    def __init__(self, integration: model.Integration) -> None:
        if integration.kind != "linkedin-ads":
            raise Exception("LinkedInAdsIntegration init called with Integration with wrong 'kind'")

        self.integration = integration

    @property
    def client(self) -> WebClient:
        return WebClient(self.integration.sensitive_config["access_token"])

    def _check_auth_error(self, response: requests.Response, context: str) -> None:
        if response.status_code == 401:
            logger.warning(
                f"LinkedInAdsIntegration: Auth error {context}",
                status_code=response.status_code,
                integration_id=self.integration.id,
            )
            self.integration.errors = common.ERROR_TOKEN_REFRESH_FAILED
            self.integration.save(update_fields=["errors"])
            raise ValidationError(
                "This integration's authentication is no longer valid. "
                "Please reconnect or disconnect this integration and connect a different account."
            )
        if response.status_code == 403:
            raise ValidationError(
                "This integration does not have permission to access this resource. "
                "Please check the account permissions on the provider side."
            )

    def list_linkedin_ads_conversion_rules(self, account_id):
        response = requests.request(
            "GET",
            f"https://api.linkedin.com/rest/conversions?q=account&account=urn%3Ali%3AsponsoredAccount%3A{account_id}&fields=conversionMethod%2Cenabled%2Ctype%2Cname%2Cid%2Ccampaigns%2CattributionType",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.integration.sensitive_config['access_token']}",
                "LinkedIn-Version": "202607",
            },
            timeout=10,
        )

        self._check_auth_error(response, "listing conversion rules")
        return response.json()

    def list_linkedin_ads_accounts(self) -> dict:
        response = requests.request(
            "GET",
            "https://api.linkedin.com/rest/adAccounts?q=search",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.integration.sensitive_config['access_token']}",
                "LinkedIn-Version": "202607",
            },
            timeout=10,
        )

        self._check_auth_error(response, "listing ad accounts")
        return response.json()
