"""Type definitions for LinkedIn Ads API responses and data structures."""

import datetime as dt
from collections.abc import Callable
from datetime import date, datetime
from typing import Any, Optional, TypedDict, Union


# Basic LinkedIn API response types
class LinkedinDateType(TypedDict):
    """LinkedIn date structure in API responses."""
    year: int
    month: int
    day: int


class LinkedinDateRangeType(TypedDict):
    """LinkedIn date range structure in API responses."""
    start: LinkedinDateType
    end: LinkedinDateType


class LinkedinVersionType(TypedDict):
    """LinkedIn version structure."""
    versionTag: str


class LinkedinAuditStampsType(TypedDict):
    """LinkedIn audit stamps for creation/modification tracking."""
    created: dict[str, int]  # {"time": timestamp}
    lastModified: dict[str, int]  # {"time": timestamp}


# Account-related types
class LinkedinAccountType(TypedDict):
    """LinkedIn Ad Account response structure."""
    id: str
    name: str
    status: str  # ACTIVE, INACTIVE, etc.
    type: str  # BUSINESS, ENTERPRISE, etc.
    currency: str  # USD, EUR, etc.
    version: LinkedinVersionType


# Campaign-related types
class LinkedinCampaignType(TypedDict):
    """LinkedIn Campaign response structure."""
    id: str
    name: str
    account: str  # URN format: urn:li:sponsoredAccount:123456789
    campaignGroup: Optional[str]  # URN format
    status: str  # ACTIVE, PAUSED, etc.
    type: str  # SPONSORED_CONTENT, etc.
    changeAuditStamps: LinkedinAuditStampsType
    runSchedule: Optional[dict[str, Any]]  # Complex schedule object
    dailyBudget: Optional[dict[str, str]]  # {"currencyCode": "USD", "amount": "100"}
    unitCost: Optional[dict[str, str]]  # {"currencyCode": "USD", "amount": "1.50"}
    costType: Optional[str]  # CPM, CPC, etc.
    targetingCriteria: Optional[dict[str, Any]]  # Complex targeting object
    locale: Optional[dict[str, str]]  # {"country": "US", "language": "en"}
    version: LinkedinVersionType


# Campaign Group types
class LinkedinCampaignGroupType(TypedDict):
    """LinkedIn Campaign Group response structure."""
    id: str
    name: str
    account: str  # URN format
    status: str  # ACTIVE, PAUSED, etc.
    runSchedule: Optional[dict[str, Any]]
    totalBudget: Optional[dict[str, str]]  # {"currencyCode": "USD", "amount": "1000"}
    changeAuditStamps: LinkedinAuditStampsType


# Analytics types
class LinkedinAnalyticsType(TypedDict):
    """LinkedIn Analytics response structure."""
    impressions: int
    clicks: int
    dateRange: LinkedinDateRangeType
    pivotValues: list[str]  # URN values for campaigns/creatives/etc.
    costInUsd: str  # String representation of decimal
    externalWebsiteConversions: int
    landingPageClicks: int
    totalEngagements: int
    videoViews: int
    videoCompletions: int
    oneClickLeads: int
    follows: int


# Flattened data types (after processing)
class FlattenedLinkedinDataType(TypedDict, total=False):
    """Flattened LinkedIn data structure for warehouse storage."""
    # Common fields that may be present in any resource
    id: Optional[str]
    name: Optional[str]
    status: Optional[str]

    # Date fields (flattened from dateRange)
    date_range_start: Optional[date]
    date_range_end: Optional[date]

    # Analytics fields (may be present in stats resources)
    impressions: Optional[int]
    clicks: Optional[int]
    cost_in_usd: Optional[float]  # Converted from string
    external_website_conversions: Optional[int]
    landing_page_clicks: Optional[int]
    total_engagements: Optional[int]
    video_views: Optional[int]
    video_completions: Optional[int]
    one_click_leads: Optional[int]
    follows: Optional[int]

    # Pivot fields (extracted from pivotValues)
    campaign_id: Optional[str]
    campaign_group_id: Optional[str]
    creative_id: Optional[str]

    # Account fields
    account_type: Optional[str]
    currency: Optional[str]
    version_tag: Optional[str]

    # Campaign fields
    account_urn: Optional[str]
    campaign_group_urn: Optional[str]
    campaign_type: Optional[str]
    cost_type: Optional[str]
    created_time: Optional[datetime]
    last_modified_time: Optional[datetime]

    # Campaign group fields
    total_budget_amount: Optional[str]
    total_budget_currency: Optional[str]


# API response wrapper types
class LinkedinApiResponseType(TypedDict):
    """LinkedIn API response wrapper structure."""
    elements: list[Union[LinkedinAccountType, LinkedinCampaignType, LinkedinCampaignGroupType, LinkedinAnalyticsType]]
    metadata: Optional[dict[str, Any]]  # Contains pagination info


class LinkedinApiMetadataType(TypedDict, total=False):
    """LinkedIn API response metadata structure."""
    nextPageToken: Optional[str]
    count: Optional[int]
    start: Optional[int]


# Function signature types for better type safety
LinkedinApiMethod = Callable[..., list[dict[str, Any]]]
ResourceMethodTuple = tuple[LinkedinApiMethod, Optional[str]]  # (method, pivot)

# Config types - these are truly dynamic from external sources
ConfigType = Any  # Config comes from external source, structure varies
IncrementalValue = Union[str, date, datetime, int, None]  # Values from database can be various types

# Request/Response types for HTTP layer
RequestParams = dict[str, Union[str, int]]
ResponseData = dict[str, Any]  # API responses can have varying structure

# Date calculation types
DateRange = tuple[dt.datetime, dt.datetime]
OptionalDateRange = tuple[Optional[str], Optional[str]]
