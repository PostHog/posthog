import datetime as dt
from collections.abc import Generator
from typing import Any, Optional
from urllib.parse import urlencode

import requests

from .schemas import PinterestAdsResource, RESOURCE_SCHEMAS

API_BASE_URL = "https://api.pinterest.com/v5"
MAX_PAGE_SIZE = 250
ANALYTICS_WINDOW_DAYS = 89


class PinterestAdsClient:
    """Pinterest Ads API client."""

    def __init__(self, access_token: str):
        if not access_token:
            raise ValueError("Access token required")
        self.access_token = access_token
        self.base_url = API_BASE_URL
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {access_token}"})

    def get_campaigns(
        self, ad_account_id: str, updated_since: Optional[int] = None
    ) -> Generator[list[dict[str, Any]], None, None]:
        """Get campaigns with pagination."""
        params: dict[str, Any] = {"page_size": MAX_PAGE_SIZE}
        if updated_since:
            params["entity_statuses"] = "ACTIVE,PAUSED,ARCHIVED"
            params["updated_since"] = updated_since

        url = f"{self.base_url}/ad_accounts/{ad_account_id}/campaigns"
        yield from self._paginate(url, params)

    def get_ad_groups(
        self, ad_account_id: str, updated_since: Optional[int] = None
    ) -> Generator[list[dict[str, Any]], None, None]:
        """Get ad groups with pagination."""
        params: dict[str, Any] = {"page_size": MAX_PAGE_SIZE}
        if updated_since:
            params["entity_statuses"] = "ACTIVE,PAUSED,ARCHIVED"
            params["updated_since"] = updated_since

        url = f"{self.base_url}/ad_accounts/{ad_account_id}/ad_groups"
        yield from self._paginate(url, params)

    def get_ads(
        self, ad_account_id: str, updated_since: Optional[int] = None
    ) -> Generator[list[dict[str, Any]], None, None]:
        """Get ads with pagination."""
        params: dict[str, Any] = {"page_size": MAX_PAGE_SIZE}
        if updated_since:
            params["entity_statuses"] = "ACTIVE,PAUSED,ARCHIVED,REJECTED,APPROVED,PENDING"
            params["updated_since"] = updated_since

        url = f"{self.base_url}/ad_accounts/{ad_account_id}/ads"
        yield from self._paginate(url, params)

    def get_analytics(
        self,
        ad_account_id: str,
        resource: PinterestAdsResource,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        """Get analytics data for campaigns, ad groups, or ads."""
        if resource == PinterestAdsResource.CampaignAnalytics:
            endpoint = "campaigns/analytics"
            id_field = "CAMPAIGN_ID"
        elif resource == PinterestAdsResource.AdGroupAnalytics:
            endpoint = "ad_groups/analytics"
            id_field = "AD_GROUP_ID"
        elif resource == PinterestAdsResource.AdAnalytics:
            endpoint = "ads/analytics"
            id_field = "AD_ID"
        else:
            raise ValueError(f"Unsupported analytics resource: {resource}")

        url = f"{self.base_url}/ad_accounts/{ad_account_id}/{endpoint}"

        columns = ",".join(RESOURCE_SCHEMAS[resource]["field_names"])

        params = {
            "start_date": start_date,
            "end_date": end_date,
            "granularity": "DAY",
            "columns": columns,
        }

        response = self.session.get(url, params=params)

        if response.status_code != 200:
            error_msg = f"Pinterest API error ({response.status_code})"
            try:
                error_data = response.json()
                if "message" in error_data:
                    error_msg = f"{error_msg}: {error_data['message']}"
            except Exception:
                error_msg = f"{error_msg}: {response.text}"
            raise Exception(error_msg)

        data = response.json()

        if not isinstance(data, list):
            return []

        return data

    def get_data_by_resource(
        self,
        resource: PinterestAdsResource,
        ad_account_id: str,
        updated_since: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Generator[list[dict[str, Any]], None, None]:
        """Get data by resource type."""
        if resource == PinterestAdsResource.Campaigns:
            yield from self.get_campaigns(ad_account_id, updated_since)
        elif resource == PinterestAdsResource.AdGroups:
            yield from self.get_ad_groups(ad_account_id, updated_since)
        elif resource == PinterestAdsResource.Ads:
            yield from self.get_ads(ad_account_id, updated_since)
        elif resource in [
            PinterestAdsResource.CampaignAnalytics,
            PinterestAdsResource.AdGroupAnalytics,
            PinterestAdsResource.AdAnalytics,
        ]:
            if not start_date or not end_date:
                raise ValueError("start_date and end_date required for analytics resources")
            yield self.get_analytics(ad_account_id, resource, start_date, end_date)
        else:
            raise ValueError(f"Unsupported resource: {resource}")

    def _paginate(self, url: str, params: dict[str, Any]) -> Generator[list[dict[str, Any]], None, None]:
        """Generic pagination handler for Pinterest API."""
        bookmark = None

        while True:
            current_params = params.copy()
            if bookmark:
                current_params["bookmark"] = bookmark

            response = self.session.get(url, params=current_params)

            if response.status_code != 200:
                error_msg = f"Pinterest API error ({response.status_code})"
                try:
                    error_data = response.json()
                    if "message" in error_data:
                        error_msg = f"{error_msg}: {error_data['message']}"
                except Exception:
                    error_msg = f"{error_msg}: {response.text}"
                raise Exception(error_msg)

            data = response.json()
            items = data.get("items", [])

            if not items:
                break

            yield items

            bookmark = data.get("bookmark")
            if not bookmark:
                break
