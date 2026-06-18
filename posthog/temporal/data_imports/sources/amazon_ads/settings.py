from dataclasses import dataclass
from typing import Optional


@dataclass
class AmazonAdsEndpointConfig:
    name: str
    # Path under the regional advertising host.
    path: str
    primary_key: str
    # Sponsored Products v3 list endpoints are POSTs with vendor media types
    # and are scoped to a profile via the Amazon-Advertising-API-Scope header.
    profile_scoped: bool = False
    media_type: Optional[str] = None
    # Key the rows live under in the response body (None = bare array).
    data_key: Optional[str] = None


# Entity lists only — Amazon Ads performance metrics ship via the async
# reporting API (create report → poll → download gzip), a follow-up. Entity
# endpoints have no updated-since filter, so every stream is a full refresh.
AMAZON_ADS_ENDPOINTS: dict[str, AmazonAdsEndpointConfig] = {
    "profiles": AmazonAdsEndpointConfig(
        name="profiles",
        path="/v2/profiles",
        primary_key="profileId",
    ),
    "sp_campaigns": AmazonAdsEndpointConfig(
        name="sp_campaigns",
        path="/sp/campaigns/list",
        primary_key="campaignId",
        profile_scoped=True,
        media_type="application/vnd.spCampaign.v3+json",
        data_key="campaigns",
    ),
    "sp_ad_groups": AmazonAdsEndpointConfig(
        name="sp_ad_groups",
        path="/sp/adGroups/list",
        primary_key="adGroupId",
        profile_scoped=True,
        media_type="application/vnd.spAdGroup.v3+json",
        data_key="adGroups",
    ),
}

ENDPOINTS = tuple(AMAZON_ADS_ENDPOINTS.keys())
